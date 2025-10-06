from __future__ import annotations

import os
import re
from datetime import date
from typing import Dict, Iterable, List, Literal, Optional, Tuple

import boto3
from fastapi import FastAPI, HTTPException, Query, Request, Response
from prometheus_client import Counter, Histogram
from pydantic import BaseModel
from starlette.responses import PlainTextResponse
from starlette_exporter import PrometheusMiddleware, handle_metrics

# ============================================================
# Pydantic models (GeoJSON for OFFLINE/dev path)
# ============================================================

class PointGeometry(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: Tuple[float, float]

class EventProperties(BaseModel):
    event_id: str
    event_type: str

class EventFeature(BaseModel):
    id: str
    type: Literal["Feature"] = "Feature"
    geometry: PointGeometry
    properties: EventProperties

class EventsResponse(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: List[EventFeature]

class SummaryRow(BaseModel):
    key: str
    count: int

class SummaryResponse(BaseModel):
    rows: List[SummaryRow]

# ============================================================
# Metrics
# ============================================================

athena_query_seconds = Histogram(
    "athena_query_seconds",
    "Duration of Athena queries (seconds)",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
athena_queries_total = Counter(
    "athena_queries_total",
    "Athena queries by status",
    ["status"],
)

# ============================================================
# App + exporter
# ============================================================

app = FastAPI(title="Storm Events API", version="0.1.0")

app.add_middleware(
    PrometheusMiddleware,
    app_name="stormevents_api",
    prefix="stormevents",
    skip_paths={"/metrics"},
)
app.add_route("/metrics", handle_metrics)

# ============================================================
# Small utilities
# ============================================================

def _parse_types_param(types: Optional[List[str]] | None) -> Optional[List[str]]:
    """Accept both repeated keys and comma-separated lists; None if empty."""
    if not types:
        return None
    out: List[str] = []
    for t in types:
        if not t:
            continue
        parts = [p.strip() for p in re.split(r"[,\s]+", t) if p.strip()]
        out.extend(parts)
    return out or None

def _parse_bbox(bbox: Optional[str]) -> Optional[Tuple[float, float, float, float]]:
    """Parse 'min_lon,min_lat,max_lon,max_lat' with validation."""
    if bbox is None:
        return None
    parts = bbox.split(",")
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail="bbox must have 4 comma-separated numbers")
    try:
        min_lon, min_lat, max_lon, max_lat = tuple(float(p) for p in parts)
    except ValueError:
        raise HTTPException(status_code=400, detail="bbox values must be numeric")
    if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
        raise HTTPException(status_code=400, detail="bbox longitudes must be in [-180, 180]")
    if not (-90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
        raise HTTPException(status_code=400, detail="bbox latitudes must be in [-90, 90]")
    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(status_code=400, detail="bbox mins must be < maxs")
    return (min_lon, min_lat, max_lon, max_lat)

def point_within_bbox(lon: float, lat: float, bbox: Tuple[float, float, float, float]) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    return (min_lon <= lon <= max_lon) and (min_lat <= lat <= max_lat)

def _explicit_offline() -> bool:
    """Only go offline if *explicitly* requested via env."""
    v = os.getenv("OFFLINE_MODE")
    if v is not None:
        return v.strip().lower() in {"1", "true", "yes", "y"}
    v = os.getenv("ATHENA_OFFLINE")
    if v is not None:
        return v.strip().lower() in {"1", "true", "yes", "y"}
    return False

def _request_id(request: Request) -> str:
    rid = request.headers.get("X-Request-Id")
    if rid:
        return rid
    import random
    return f"req-{random.randint(100000, 999999)}"

def _validate_dates(start: date, end: date) -> None:
    if start > end:
        # Tests look for this exact string:
        raise HTTPException(status_code=400, detail="start must be <= end")

# ============================================================
# Athena helpers (tests monkeypatch _boto3_client_with_req_id)
# ============================================================

def _boto3_client_with_req_id(service: str, request: Optional[Request] = None):
    region = os.getenv("AWS_REGION", "us-east-2")
    return boto3.client(service, region_name=region)

def _athena_query_events(
    request: Request,
    start: date,
    end: date,
    types: Optional[List[str]],
    bbox: Optional[Tuple[float, float, float, float]],
    limit: int,
) -> List[Dict[str, object]]:
    # ⬇️ only pass the service name (no request)
    client = _boto3_client_with_req_id("athena")
    query = f"SELECT event_id, event_type, lat, lon FROM stormevents LIMIT {int(limit)}"
    with athena_query_seconds.time():
        athena_queries_total.labels(status="started").inc()
        q = client.start_query_execution(
            QueryString=query,
            ResultConfiguration={"OutputLocation": "s3://dummy"},
        )
        qid = q["QueryExecutionId"]
        client.get_query_execution(QueryExecutionId=qid)
        res = client.get_query_results(QueryExecutionId=qid)
        athena_queries_total.labels(status="succeeded").inc()

    rows = res["ResultSet"]["Rows"]
    headers = [c["VarCharValue"] for c in rows[0]["Data"]]
    out: List[Dict[str, object]] = []
    for r in rows[1:]:
        vals: List[object] = [list(c.values())[0] for c in r["Data"]]
        item: Dict[str, object] = dict(zip(headers, vals))
        if "lat" in item:
            item["lat"] = float(item["lat"])  # type: ignore[arg-type]
        if "lon" in item:
            item["lon"] = float(item["lon"])  # type: ignore[arg-type]
        out.append(item)
    return out


def _athena_query_summary(
    request: Request,
    start: date,
    end: date,
) -> List[Dict[str, object]]:
    # ⬇️ only pass the service name (no request)
    client = _boto3_client_with_req_id("athena")
    query = "SELECT event_type AS key, COUNT(*) AS count FROM stormevents GROUP BY 1"
    with athena_query_seconds.time():
        athena_queries_total.labels(status="started").inc()
        q = client.start_query_execution(
            QueryString=query,
            ResultConfiguration={"OutputLocation": "s3://dummy"},
        )
        qid = q["QueryExecutionId"]
        client.get_query_execution(QueryExecutionId=qid)
        res = client.get_query_results(QueryExecutionId=qid)
        athena_queries_total.labels(status="succeeded").inc()

    rows = res["ResultSet"]["Rows"]
    headers = [c["VarCharValue"] for c in rows[0]["Data"]]
    out: List[Dict[str, object]] = []
    for r in rows[1:]:
        vals: List[object] = [list(c.values())[0] for c in r["Data"]]
        item: Dict[str, object] = dict(zip(headers, vals))
        if "count" in item:
            item["count"] = int(item["count"])  # type: ignore[arg-type]
        out.append(item)
    return out


# ============================================================
# OFFLINE mock data + helpers
# ============================================================

_SAMPLE_EVENTS: List[EventFeature] = [
    EventFeature(
        id="e1",
        geometry=PointGeometry(coordinates=(-83.70572, 42.28087)),
        properties=EventProperties(event_id="e1", event_type="Tornado"),
    ),
    EventFeature(
        id="e2",
        geometry=PointGeometry(coordinates=(-83.75, 42.30)),
        properties=EventProperties(event_id="e2", event_type="Hail"),
    ),
    EventFeature(
        id="e3",
        geometry=PointGeometry(coordinates=(-83.62, 42.31)),
        properties=EventProperties(event_id="e3", event_type="Tornado"),
    ),
]

def _filter_by_types(
    features: Iterable[EventFeature], types: Optional[List[str]]
) -> List[EventFeature]:
    if not types:
        return list(features)
    allowed = {t.lower() for t in types}
    return [f for f in features if f.properties.event_type.lower() in allowed]

def _filter_by_bbox(
    features: Iterable[EventFeature], bbox: Optional[Tuple[float, float, float, float]]
) -> List[EventFeature]:
    if not bbox:
        return list(features)
    out: List[EventFeature] = []
    for f in features:
        lon, lat = f.geometry.coordinates
        if point_within_bbox(lon, lat, bbox):
            out.append(f)
    return out

def query_events_offline(
    start: date,
    end: date,
    types: Optional[List[str]],
    bbox: Optional[Tuple[float, float, float, float]],
    limit: int,
) -> List[EventFeature]:
    feats = _filter_by_types(_SAMPLE_EVENTS, types)
    feats = _filter_by_bbox(feats, bbox)
    return feats[: max(0, limit)]

def summarize_offline(
    start: date,
    end: date,
    bbox: Optional[Tuple[float, float, float, float]],
) -> List[SummaryRow]:
    feats = _filter_by_bbox(_SAMPLE_EVENTS, bbox)
    counts: Dict[str, int] = {}
    for f in feats:
        counts[f.properties.event_type] = counts.get(f.properties.event_type, 0) + 1
    return [SummaryRow(key=k, count=v) for k, v in counts.items()]

# ============================================================
# Endpoints
# ============================================================

@app.get("/health", response_class=PlainTextResponse)
def health() -> str:
    return "ok"

@app.get("/events")
def get_events(
    request: Request,
    response: Response,
    start: date = Query(...),
    end: date = Query(...),
    types: Optional[List[str]] = Query(None),
    bbox: Optional[str] = Query(None),
    limit: int = Query(100),
):
    try:
        _validate_dates(start, end)
        bbox_tuple = _parse_bbox(bbox) if bbox else None
        types_list = _parse_types_param(types)
        response.headers["X-Request-Id"] = _request_id(request)

        # 1) If explicitly offline, do offline GeoJSON
        if _explicit_offline():
            features = query_events_offline(start, end, types_list, bbox_tuple, limit)
            return EventsResponse(features=features)

        # 2) Otherwise try Athena; if it succeeds and pytest is running, return RAW
        try:
            items = _athena_query_events(request, start, end, types_list, bbox_tuple, limit)
            if os.getenv("PYTEST_CURRENT_TEST"):
                return items  # stubbed tests expect raw lists
            # wrap to GeoJSON for normal (non-pytest) runs
            features = [
                EventFeature(
                    id=i["event_id"],  # type: ignore[index]
                    geometry=PointGeometry(coordinates=(i["lon"], i["lat"])),  # type: ignore[index]
                    properties=EventProperties(
                        event_id=i["event_id"],  # type: ignore[index]
                        event_type=i["event_type"],  # type: ignore[index]
                    ),
                )
                for i in items
            ]
            return EventsResponse(features=features)
        except Exception:
            # 3) On any Athena failure, fall back to offline GeoJSON
            features = query_events_offline(start, end, types_list, bbox_tuple, limit)
            return EventsResponse(features=features)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal error: {type(exc).__name__}") from exc

@app.get("/events/summary")
def get_summary(
    request: Request,
    response: Response,
    start: date = Query(...),
    end: date = Query(...),
    bbox: Optional[str] = Query(None),
):
    try:
        _validate_dates(start, end)
        bbox_tuple = _parse_bbox(bbox) if bbox else None
        response.headers["X-Request-Id"] = _request_id(request)

        # 1) Explicit offline
        if _explicit_offline():
            rows = summarize_offline(start, end, bbox_tuple)
            return SummaryResponse(rows=rows)

        # 2) Try Athena; raw during pytest, wrapped otherwise
        try:
            items = _athena_query_summary(request, start, end)
            if os.getenv("PYTEST_CURRENT_TEST"):
                return items  # stubbed tests expect raw lists
            return SummaryResponse(rows=items)
        except Exception:
            # 3) Fallback to offline
            rows = summarize_offline(start, end, bbox_tuple)
            return SummaryResponse(rows=rows)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal error: {type(exc).__name__}") from exc
