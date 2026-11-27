"""GET /api/v1/live/stops: остановки в видимой области карты (образцы ЦУГАЭТ)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters.fake.feed import FakeTransitFeed
from app.config import Settings
from app.domain.models import Direction
from app.main import create_app
from tests.conftest import SAMPLES, ManualClock
from tests.test_stop_api import bus3_stops


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
    stops = bus3_stops(Direction.A)
    origin = next(stop.point for stop in stops if "Лермонтова" in stop.name)
    destination = stops[-1].point
    area = bbox((origin.lat, origin.lon), (destination.lat, destination.lon))
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
