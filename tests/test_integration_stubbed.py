import importlib
import boto3
from botocore.stub import Stubber, ANY
from fastapi.testclient import TestClient


def _headers_row(columns):
    return {"Data": [{"VarCharValue": c} for c in columns]}


def _data_row(values):
    return {"Data": [{"VarCharValue": str(v)} for v in values]}


class _NoopMetric:
    def __init__(self, *a, **kw): ...
    def labels(self, *a, **kw): return self
    def observe(self, *a, **kw): ...
    def inc(self, *a, **kw): ...
    def time(self):
        class _Ctx:
            def __enter__(self): return self
            def __exit__(self, *exc): ...
        return _Ctx()


def _fresh_app_with_athena(monkeypatch):
    """
    Disable OFFLINE_MODE so the Athena path is used.
    Stub Prometheus metrics to avoid duplicate registration when reloading.
    """
    monkeypatch.setenv("OFFLINE_MODE", "0")

    # Prevent metrics registration on reload
    monkeypatch.setattr("prometheus_client.Histogram", _NoopMetric, raising=True)
    monkeypatch.setattr("prometheus_client.Counter", _NoopMetric, raising=True)
    monkeypatch.setattr("prometheus_client.Gauge", _NoopMetric, raising=True)
    monkeypatch.setattr("prometheus_client.Summary", _NoopMetric, raising=True)

    # (Re)load the app AFTER stubs & env are set
    from api import app as app_module
    importlib.reload(app_module)
    return app_module.app


def _normalize_events_payload(payload):
    """
    Return a list of {event_id,event_type,lat,lon} regardless of payload shape.
    Supports:
      - GeoJSON FeatureCollection
      - List of dicts already in the target shape
    """
    if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
        feats = payload.get("features", [])
        out = []
        for f in feats:
            props = f.get("properties", {})
            coords = (f.get("geometry", {}) or {}).get("coordinates", [None, None])
            # coords = [lon, lat]
            out.append({
                "event_id": props.get("event_id"),
                "event_type": props.get("event_type"),
                "lat": coords[1],
                "lon": coords[0],
            })
        return out
    elif isinstance(payload, list):
        return payload
    else:
        raise AssertionError(f"Unexpected /events payload shape: {type(payload)} -> {payload}")


def _normalize_summary_payload(payload):
    """
    Return a list of {key,count} regardless of payload shape.
    Supports:
      - {"rows": [...]}
      - List of dicts already in the target shape
    """
    if isinstance(payload, dict) and "rows" in payload:
        return payload["rows"]
    elif isinstance(payload, list):
        return payload
    else:
        raise AssertionError(f"Unexpected /events/summary payload shape: {type(payload)} -> {payload}")


def test_events_stubbed(monkeypatch):
    app = _fresh_app_with_athena(monkeypatch)

    athena = boto3.client("athena", region_name="us-east-2")
    stub = Stubber(athena)

    # Make the app use our stubbed client
    monkeypatch.setattr("api.app._boto3_client_with_req_id", lambda service: athena)

    # Expect real params but accept any values
    stub.add_response(
        "start_query_execution",
        {"QueryExecutionId": "QID-123"},
        {"QueryString": ANY, "ResultConfiguration": {"OutputLocation": ANY}},
    )
    stub.add_response(
        "get_query_execution",
        {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}},
        {"QueryExecutionId": "QID-123"},
    )

    headers = ["event_id", "event_type", "lat", "lon"]
    rows = [
        _headers_row(headers),
        _data_row(["e1", "Tornado", 42.28, -83.7]),
        _data_row(["e2", "Hail", 42.3, -83.75]),
    ]
    stub.add_response(
        "get_query_results",
        {"ResultSet": {"Rows": rows}},
        {"QueryExecutionId": "QID-123"},
    )
    stub.activate()

    client = TestClient(app)
    resp = client.get(
        "/events",
        params=dict(start="2020-01-01", end="2020-01-31", bbox="-84,42,-83,43", limit=10),
    )
    assert resp.status_code == 200

    events = _normalize_events_payload(resp.json())
    assert events == [
        {"event_id": "e1", "event_type": "Tornado", "lat": 42.28, "lon": -83.7},
        {"event_id": "e2", "event_type": "Hail",    "lat": 42.3,  "lon": -83.75},
    ]


def test_summary_stubbed(monkeypatch):
    app = _fresh_app_with_athena(monkeypatch)

    athena = boto3.client("athena", region_name="us-east-2")
    stub = Stubber(athena)

    monkeypatch.setattr("api.app._boto3_client_with_req_id", lambda service: athena)

    stub.add_response(
        "start_query_execution",
        {"QueryExecutionId": "QID-456"},
        {"QueryString": ANY, "ResultConfiguration": {"OutputLocation": ANY}},
    )
    stub.add_response(
        "get_query_execution",
        {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}},
        {"QueryExecutionId": "QID-456"},
    )

    headers = ["key", "count"]
    rows = [
        _headers_row(headers),
        _data_row(["Tornado", 12]),
        _data_row(["Hail", 4]),
    ]
    stub.add_response(
        "get_query_results",
        {"ResultSet": {"Rows": rows}},
        {"QueryExecutionId": "QID-456"},
    )
    stub.activate()

    client = TestClient(app)
    resp = client.get(
        "/events/summary",
        params=dict(start="2020-01-01", end="2020-01-31", groupby="type"),
    )
    assert resp.status_code == 200

    rows_norm = _normalize_summary_payload(resp.json())
    assert rows_norm == [
        {"key": "Tornado", "count": 12},
        {"key": "Hail",    "count": 4},
    ]
