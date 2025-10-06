from fastapi.testclient import TestClient
from api.app import app


def test_health_ok():
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    assert r.text == "ok"
