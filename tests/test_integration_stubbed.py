import os
import importlib
import boto3
from botocore.stub import Stubber, ANY
from fastapi.testclient import TestClient


def _headers_row(columns):
    """Athena first row contains column headers."""
    return {"Data": [{"VarCharValue": c} for c in columns]}


def _data_row(values):
    """Athena rows return all values as strings; stringify to match."""
    return {"Data": [{"VarCharValue": str(v)} for v in values]}


def _fresh_app_with_athena(monkeypatch):
    """
    Ensure OFFLINE_MODE is disabled and reload FastAPI app module
    so requests go through the Athena code path.
    """
    # Turn OFF offline mode for this test run
    monkeypatch.setenv("OFFLINE_MODE", "0")
    # If your code uses a different toggle, set it here as well:
    # monkeypatch.setenv("USE_ATHENA", "1")

    # Import/reload app AFTER env is set so startup reads new values
    from api import app as app_module

    importlib.reload(app_module)
    return app_module.app


def test_events_stubbed(monkeypatch):
    """
    /events should return parsed rows from Athena when the query succeeds.
    We stub all three Athena calls: start, poll, and fetch results.
    """
    app = _fresh_app_with_athena(monkeypatch)

    athena = boto3.client("athena", region_name="us-east-2")
    stub = Stubber(athena)

    # Make the app use our stubbed client
    monkeypatch.setattr("api.app._boto3_client_with_req_id", lambda service: athena)

    # Expect real params but accept any values with ANY
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

    # Current API returns a GeoJSON FeatureCollection; compare essentials
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    feats = data["features"]
    assert len(feats) == 2

    def simple_feature(f):
        # GeoJSON coordinates are [lon, lat]
        return {
            "event_id": f["properties"]["event_id"],
            "event_type": f["properties"]["event_type"],
            "coordinates": f["geometry"]["coordinates"],
        }

    assert [simple_feature(f) for f in feats] == [
        {"event_id": "e1", "event_type": "Tornado", "coordinates": [-83.7, 42.28]},
        {"event_id": "e2", "event_type": "Hail", "coordinates": [-83.75, 42.3]},
    ]


def test_summary_stubbed(monkeypatch):
    """
    /events/summary should return aggregated counts when the query succeeds.
    """
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

    # Current API wraps results under {"rows": [...]}
    assert resp.json()["rows"] == [
        {"key": "Tornado", "count": 12},
        {"key": "Hail", "count": 4},
    ]
