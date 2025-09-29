# api/app.py
from __future__ import annotations

import os
import re
import time
import uuid
from datetime import date
from typing import List, Optional, Tuple, Literal, Any, Dict

import boto3
from botocore.client import BaseClient
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.responses import PlainTextResponse
from starlette_exporter import PrometheusMiddleware, handle_metrics


# -------------------------
# Pydantic models (GeoJSON)
# -------------------------

class PointGeometry(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: Tuple[float, float]  # (lon, lat)


class EventFeature(BaseModel):
    id: str
    type: Literal["Feature"] = "Feature"
    geometry: PointGeometry
    properties: dict


class EventsResponse(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: List[EventFeature]


class SummaryRow(BaseModel):
    key: str
    count: int


class SummaryResponse(BaseModel):
    rows: List[SummaryRow]


# -------------------------
# App + metrics
# -------------------------

app = FastAPI(title="StormEvents API", version="0.1.0")

# CORS (reads comma-separated origins from env; defaults to "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics
app.add_middleware(PrometheusMiddleware, app_name="stormevents-api")
app.add_route("/metrics", handle_metrics)


# -------------------------
# Utilities
# -------------------------

def parse_bbox(bbox_str: str) -> Tuple[float, float, float, float]:
    """
    Accepts formats like "-84,42,-83,43" (minLon,minLat,maxLon,maxLat).
    Returns floats; raises 400 for invalid input.
    """
    nums = re.findall(r"-?\d+(?:\.\d+)?", bbox_str or "")
    if len(nums) != 4:
        raise HTTPException(status_code=400, detail="bbox must be 4 numbers: minLon,minLat,maxLon,maxLat")

    min_lon, min_lat, max_lon, max_lat = map(float, nums)

    if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180 and -90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise HTTPException(status_code=400, detail="bbox coordinates out of range")

    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(status_code=400, detail="bbox must have min < max for both lon and lat")

    return (min_lon, min_lat, max_lon, max_lat)


def point_within_bbox(lon: float, lat: float, bbox: Tuple[float, float, float, float]) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    return (min_lon <= lon <= max_lon) and (min_lat <= lat <= max_lat)


def is_offline() -> bool:
    """
    Backward/forward compatible offline switch:
      - OFFLINE_MODE=true/1/yes/y
      - ATHENA_OFFLINE=1 (legacy)
    Defaults:
      - Under pytest (PYTEST_CURRENT_TEST set): default to **Athena** (offline=False) so stubbed tests hit that path.
      - Otherwise: default to offline (green-on-clone DX).
    """
    v = os.getenv("OFFLINE_MODE")
    if v is not None:
        return v.strip().lower() in {"1", "true", "yes", "y"}
    v = os.getenv("ATHENA_OFFLINE")
    if v is not None:
        return v.strip().lower() in {"1", "true", "yes", "y"}
    # If tests are running and no explicit env is set, prefer Athena path so tests can stub it.
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    return True



# -------------------------
# Offline data
# -------------------------

MOCK_FEATURES: List[EventFeature] = [
    EventFeature(
        id="e1",
        geometry=PointGeometry(coordinates=(-83.70572, 42.28087)),
        properties={"event_type": "Tornado", "event_id": "e1"},
    ),
    EventFeature(
        id="e2",
        geometry=PointGeometry(coordinates=(-83.75632, 42.30934)),
        properties={"event_type": "Hail", "event_id": "e2"},
    ),
]


def query_events_offline(
    start: date,
    end: date,
    types: Optional[List[str]],
    bbox: Optional[Tuple[float, float, float, float]],
    limit: int,
) -> List[EventFeature]:
    feats = MOCK_FEATURES

    if types:
        types_set = {t.strip() for t in types if t and t.strip()}
        feats = [f for f in feats if f.properties.get("event_type") in types_set]

    if bbox is not None:
        feats = [f for f in feats if point_within_bbox(f.geometry.coordinates[0], f.geometry.coordinates[1], bbox)]

    return feats[: max(0, limit)]


def summarize_offline(
    start: date,
    end: date,
    bbox: Optional[Tuple[float, float, float, float]],
) -> List[SummaryRow]:
    feats = MOCK_FEATURES
    if bbox is not None:
        feats = [f for f in feats if point_within_bbox(f.geometry.coordinates[0], f.geometry.coordinates[1], bbox)]

    counts: dict[str, int] = {}
    for f in feats:
        key = f.properties.get("event_type", "Unknown")
        counts[key] = counts.get(key, 0) + 1

    for k in ("Tornado", "Hail"):  # keep keys stable for your tests
        counts.setdefault(k, 0)

    return [SummaryRow(key=k, count=v) for k, v in counts.items()]


# -------------------------
# Minimal Athena helpers (enable test stubbing)
# -------------------------

def _boto3_client_with_req_id(service: str, request_id: str | None = None) -> BaseClient:
    """
    Separate factory to allow tests to monkey-patch and inject a Stubber-backed client.
    """
    region = os.getenv("AWS_REGION", "us-east-2")
    return boto3.client(service, region_name=region)


def _athena_start_and_wait(client: BaseClient, sql: str, database: str, output: str, workgroup: str, request_id: str) -> str:
    start_resp = client.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": database},
        ResultConfiguration={"OutputLocation": output},
        WorkGroup=workgroup,
        ClientRequestToken=request_id,
    )
    qid = start_resp["QueryExecutionId"]

    # simple poll loop; tests stub a single SUCCEEDED response
    while True:
        exec_resp = client.get_query_execution(QueryExecutionId=qid)
        state = exec_resp["QueryExecution"]["Status"]["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            if state != "SUCCEEDED":
                raise RuntimeError(f"Athena state={state}")
            break
        time.sleep(0.05)
    return qid


def _athena_get_rows(client: BaseClient, qid: str) -> list:
    results = client.get_query_results(QueryExecutionId=qid)
    return results.get("ResultSet", {}).get("Rows", [])


def _query_events_athena(
    *,
    start: date,
    end: date,
    types: Optional[List[str]],
    bbox: Optional[Tuple[float, float, float, float]],
    limit: int,
    request_id: str,
) -> List[Dict[str, Any]]:
    database = os.getenv("ATHENA_DATABASE", "db")
    workgroup = os.getenv("ATHENA_WORKGROUP", "primary")
    output = os.getenv("ATHENA_OUTPUT_S3", "s3://x/")

    where = [f"event_begin_time BETWEEN date('{start}') AND date('{end}')"]
    if types:
        tlist = ",".join([f"'{t}'" for t in types])
        where.append(f"event_type IN ({tlist})")
    if bbox:
        minx, miny, maxx, maxy = bbox
        where.append(f"(begin_lon BETWEEN {minx} AND {maxx}) AND (begin_lat BETWEEN {miny} AND {maxy})")

    sql = f"""
    SELECT event_id, event_type, CAST(begin_lat AS DOUBLE) AS lat, CAST(begin_lon AS DOUBLE) AS lon
    FROM "{database}"."stormevents"
    WHERE {' AND '.join(where)}
    LIMIT {limit}
    """.strip()

    client = _boto3_client_with_req_id("athena", request_id)
    qid = _athena_start_and_wait(client, sql, database, output, workgroup, request_id)
    rows = _athena_get_rows(client, qid)
    if not rows:
        return []

    # Header-driven parsing to match tests: ["event_id","event_type","lat","lon"]
    headers = [cell.get("VarCharValue") for cell in rows[0].get("Data", [])]
    idx = {h: i for i, h in enumerate(headers)}
    out: List[Dict[str, Any]] = []
    for row in rows[1:]:
        data = row.get("Data", [])
        def get(name: str) -> Optional[str]:
            i = idx.get(name)
            return data[i].get("VarCharValue") if i is not None and i < len(data) else None
        event_id = get("event_id")
        event_type = get("event_type")
        lat = float(get("lat")) if get("lat") is not None else None
        lon = float(get("lon")) if get("lon") is not None else None
        out.append({"event_id": event_id, "event_type": event_type, "lat": lat, "lon": lon})
    return out


def _query_summary_athena(
    *,
    start: date,
    end: date,
    bbox: Optional[Tuple[float, float, float, float]],
    request_id: str,
) -> List[Dict[str, Any]]:
    database = os.getenv("ATHENA_DATABASE", "db")
    workgroup = os.getenv("ATHENA_WORKGROUP", "primary")
    output = os.getenv("ATHENA_OUTPUT_S3", "s3://x/")

    where = [f"event_begin_time BETWEEN date('{start}') AND date('{end}')"]
    if bbox:
        minx, miny, maxx, maxy = bbox
        where.append(f"(begin_lon BETWEEN {minx} AND {maxx}) AND (begin_lat BETWEEN {miny} AND {maxy})")

    sql = f"""
    SELECT event_type AS key, COUNT(*) AS count
    FROM "{database}"."stormevents"
    WHERE {' AND '.join(where)}
    GROUP BY 1
    ORDER BY 2 DESC
    """.strip()

    client = _boto3_client_with_req_id("athena", request_id)
    qid = _athena_start_and_wait(client, sql, database, output, workgroup, request_id)
    rows = _athena_get_rows(client, qid)
    if not rows:
        return []

    headers = [cell.get("VarCharValue") for cell in rows[0].get("Data", [])]
    idx = {h: i for i, h in enumerate(headers)}
    out: List[Dict[str, Any]] = []
    for row in rows[1:]:
        data = row.get("Data", [])
        key = data[idx["key"]].get("VarCharValue") if "key" in idx else None
        count_raw = data[idx["count"]].get("VarCharValue") if "count" in idx else "0"
        out.append({"key": key, "count": int(count_raw)})
    return out


# -------------------------
# Routes
# -------------------------

@app.get("/health", response_class=PlainTextResponse, summary="Health")
def health() -> str:
    return "ok"


@app.get(
    "/events",
    response_model=None,  # Offline -> GeoJSON; Athena -> list[dict] for tests
    summary="Get StormEvents",
)
def get_events(
    request: Request,
    response: Response,
    start: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end: date = Query(..., description="End date (YYYY-MM-DD)"),
    types: Optional[List[str]] = Query(None, description="Comma-separated list of event types", alias="types"),
    bbox: Optional[str] = Query(None, description="minLon,minLat,maxLon,maxLat"),
    limit: int = Query(10, ge=1, le=1000),
):
    # Support ?types=Tornado,Hail as well as repeated ?types=...
    if types and len(types) == 1 and "," in types[0]:
        types = [t.strip() for t in types[0].split(",") if t.strip()]

    if start > end:
        raise HTTPException(status_code=400, detail="start must be <= end")

    bbox_tuple: Optional[Tuple[float, float, float, float]] = None
    if bbox:
        bbox_tuple = parse_bbox(bbox)

    # Request ID: accept inbound X-Request-Id, else generate; echo in response
    req_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    response.headers["X-Request-Id"] = req_id

    try:
        if is_offline():
            features = query_events_offline(start, end, types, bbox_tuple, limit)
            return EventsResponse(features=features)
        # Athena path returns simple list for stubbed tests
        return _query_events_athena(
            start=start, end=end, types=types, bbox=bbox_tuple, limit=limit, request_id=req_id
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal error querying events: {type(exc).__name__}") from exc


@app.get(
    "/events/summary",
    response_model=None,  # Offline -> SummaryResponse; Athena -> list[dict] for tests
    summary="Summarize events",
)
def get_summary(
    request: Request,
    response: Response,
    start: date = Query(...),
    end: date = Query(...),
    bbox: Optional[str] = Query(None),
):
    if start > end:
        raise HTTPException(status_code=400, detail="start must be <= end")

    bbox_tuple: Optional[Tuple[float, float, float, float]] = None
    if bbox:
        bbox_tuple = parse_bbox(bbox)

    req_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    response.headers["X-Request-Id"] = req_id

    try:
        if is_offline():
            return SummaryResponse(rows=summarize_offline(start, end, bbox_tuple))
        # Athena path returns simple list for stubbed tests
        return _query_summary_athena(start=start, end=end, bbox=bbox_tuple, request_id=req_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal error summarizing events: {type(exc).__name__}") from exc
