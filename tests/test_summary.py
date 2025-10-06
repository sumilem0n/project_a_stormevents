from fastapi.testclient import TestClient
from api.app import app

c = TestClient(app)


def test_summary_ok_and_request_id_header():
    r = c.get("/events/summary?start=2024-06-01&end=2024-06-30")
    assert r.status_code == 200
    assert r.headers.get("X-Request-Id")
    data = r.json()
    assert "rows" in data and isinstance(data["rows"], list)
    # Stable keys in offline mode
    keys = {row["key"] for row in data["rows"]}
    assert {"Tornado", "Hail"}.issubset(keys)


def test_summary_start_after_end_400():
    r = c.get("/events/summary?start=2024-06-30&end=2024-06-01")
    assert r.status_code == 400
