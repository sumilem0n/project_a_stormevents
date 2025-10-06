# tests/test_integration_stubbed.py
import boto3
from botocore.stub import Stubber, ANY
from starlette.testclient import TestClient

from api.app import app


# --- small helpers to build Athena-like rows ---------------------------------
def _headers_row(cols: list[str]) -> dict:
    # Athena GetQueryResults header row
    return {"Data": [{"VarCharValue": c} for c in cols]}


def _data_row(values: list) -> dict:
    # Athena GetQueryResults data row – stringifies each value like AWS does
    return {"Data": [{"VarCharValue": str(v)} for v in values]}


# --- tests -------------------------------------------------------------------


def test_events_stubbed(monkeypatch):
    """
    /events should return parsed rows from Athena when the query succeeds.
    We stub all three Athena calls: start, poll, and fetch results.
    """
    athena = boto3.client("athena", region_name="us-east-2")
    stub = Stubber(athena)

    # make the app use our stubbed client
    monkeypatch.setattr("api.app._boto3_client_with_req_id", lambda service: athena)

    # IMPORTANT: expect the real params but accept any values with ANY
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
        params=dict(
            start="2020-01-01", end="2020-01-31", bbox="-84,42,-83,43", limit=10
        ),
    )
    assert resp.status_code == 200
    assert resp.json() == [
        {"event_id": "e1", "event_type": "Tornado", "lat": 42.28, "lon": -83.7},
        {"event_id": "e2", "event_type": "Hail", "lat": 42.3, "lon": -83.75},
    ]


def test_summary_stubbed(monkeypatch):
    """
    /events/summary should return aggregated counts when the query succeeds.
    """
    athena = boto3.client("athena", region_name="us-east-2")
    stub = Stubber(athena)

    monkeypatch.setattr("api.app._boto3_client_with_req_id", lambda service: athena)

    # IMPORTANT: expect real params, allow any values
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
    assert resp.json() == [
        {"key": "Tornado", "count": 12},
        {"key": "Hail", "count": 4},
    ]


def test_param_validation_errors():
    """
    If params are invalid (e.g., start after end), the endpoint should reject
    the request before attempting any Athena calls.
    """
    client = TestClient(app)
    resp = client.get(
        "/events",
        params=dict(start="2020-02-01", end="2020-01-01"),
    )

    # The app validates and returns a clear 400 with a message.
    assert resp.status_code == 400
    body = resp.json()
    assert "start" in body.get("detail", "").lower()
    assert "end" in body.get("detail", "").lower()
