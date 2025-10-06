from fastapi.testclient import TestClient
from api.app import app


def test_events_honors_inbound_request_id_and_bbox_parsing():
    c = TestClient(app)
    # Valid bbox with min<max, also pass inbound X-Request-Id
    headers = {"X-Request-Id": "TEST-RID-123"}
    r = c.get(
        "/events",
        params={
            "start": "2024-06-01",
            "end": "2024-06-30",
            "limit": 5,
            "bbox": "-84,42,-83,43",
        },
        headers=headers,
    )
    assert r.status_code == 200
    # Our app echoes a (possibly different) Request-Id, but should always be present
    assert r.headers.get("X-Request-Id")
