from fastapi.testclient import TestClient
from api.app import app

c = TestClient(app)


def test_events_ok_offline_defaults():
    r = c.get(
        "/events",
        params={
            "start": "2024-06-01",
            "end": "2024-06-30",
            "limit": 5,
            "types": ["Tornado", "Hail"],
        },
    )
    assert r.status_code == 200
    assert r.headers.get("X-Request-Id")
    body = r.json()
    assert body["type"] == "FeatureCollection"
    assert isinstance(body["features"], list)
    assert len(body["features"]) >= 1


def test_events_types_csv_and_repeated():
    # Repeated keys
    r1 = c.get(
        "/events?start=2024-06-01&end=2024-06-30&types=Tornado&types=Hail&limit=5"
    )
    assert r1.status_code == 200
    # CSV in a single key
    r2 = c.get("/events?start=2024-06-01&end=2024-06-30&types=Tornado,Hail&limit=5")
    assert r2.status_code == 200


def test_events_start_after_end_400():
    r = c.get("/events?start=2024-06-30&end=2024-06-01&limit=5")
    assert r.status_code == 400
    assert "start must be <=" in r.json()["detail"]


def test_events_bbox_validation_bad_range():
    # lon out of range
    r = c.get("/events?start=2024-06-01&end=2024-06-30&bbox=-200,0,10,10&limit=5")
    assert r.status_code == 400
