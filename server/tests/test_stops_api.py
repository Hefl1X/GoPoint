"""GET /api/v1/live/stops: остановки в видимой области карты (образцы ЦУГАЭТ)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters.fake.feed import FakeTransitFeed
from app.config import Settings
from app.main import create_app
from tests.conftest import SAMPLES, ManualClock
from tests.test_route_api import DEST, ORIGIN


def make_client() -> TestClient:
    app = create_app(
        Settings(transit_feed="fake"),
        feed=FakeTransitFeed(SAMPLES),
        clock=ManualClock(),
        start_poller=False,
    )
    return TestClient(app)


def bbox(*points: tuple[float, float], pad: float = 0.002) -> str:
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return f"{min(lats) - pad},{min(lons) - pad},{max(lats) + pad},{max(lons) + pad}"


def test_stops_in_area_are_unique_and_inside() -> None:
    client = make_client()
    area = bbox((ORIGIN.lat, ORIGIN.lon), (DEST.lat, DEST.lon))
    response = client.get("/api/v1/live/stops", params={"bbox": area})
    assert response.status_code == 200, response.text
    stops = response.json()["stops"]
    assert stops
    ids = [s["id"] for s in stops]
    assert len(ids) == len(set(ids))
    south, west, north, east = (float(x) for x in area.split(","))
    for s in stops:
        assert south <= s["point"]["lat"] <= north
        assert west <= s["point"]["lon"] <= east
        assert s["name"]


def test_stops_outside_area_are_not_returned() -> None:
    client = make_client()
    response = client.get("/api/v1/live/stops", params={"bbox": "10,10,10.1,10.1"})
    assert response.status_code == 200
    assert response.json()["stops"] == []


def test_stops_bad_bbox() -> None:
    client = make_client()
    response = client.get("/api/v1/live/stops", params={"bbox": "abc"})
    assert response.status_code == 422
    assert response.json()["code"] == "BAD_BBOX"


def test_stops_too_large_area_is_refused() -> None:
    """Весь город сразу не отдаём: на карте остановки видны только вблизи."""
    client = make_client()
    response = client.get("/api/v1/live/stops", params={"bbox": "54,82,56,84"})
    assert response.status_code == 422
    assert response.json()["code"] == "BAD_BBOX"
