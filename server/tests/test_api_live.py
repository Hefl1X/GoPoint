"""Адреса /live/* на сохранённых образцах ЦУГАЭТ (заглушка fake)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.adapters.fake.feed import FakeTransitFeed
from app.config import Settings
from app.main import create_app
from tests.conftest import SAMPLES, ManualClock


@pytest.fixture
def feed() -> FakeTransitFeed:
    return FakeTransitFeed(SAMPLES)


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def client(feed: FakeTransitFeed, clock: ManualClock) -> TestClient:
    app = create_app(Settings(transit_feed="fake"), feed=feed, clock=clock, start_poller=False)
    return TestClient(app)


def vehicles(client: TestClient, **params: Any) -> list[dict[str, Any]]:
    response = client.get("/api/v1/live/vehicles", params=params)
    assert response.status_code == 200, response.text
    result: list[dict[str, Any]] = response.json()["vehicles"]
    return result


def test_default_is_low_floor_only(client: TestClient) -> None:
    result = vehicles(client)
    assert result
    assert {v["lowFloor"] for v in result} == {"yes"}


def test_low_floor_off_returns_all_on_line_with_mark(client: TestClient) -> None:
    on = vehicles(client, lowFloorOnly="true")
    off = vehicles(client, lowFloorOnly="false")
    assert len(off) > len(on)
    assert {v["lowFloor"] for v in off} == {"yes", "no"}


def test_parked_lunch_and_stale_vehicles_are_hidden(client: TestClient) -> None:
    ids = {v["id"] for v in vehicles(client, lowFloorOnly="false")}
    # В образце 36 машин, на линии 32. Одна из них отметилась в 12:22:02,
    # а часы стоят на 12:28: это старше 5 минут, машина не показывается.
    assert len(ids) == 31


def test_vehicle_json_shape(client: TestClient) -> None:
    v = vehicles(client)[0]
    assert set(v["point"]) == {"lat", "lon"}
    assert v["direction"] in {"A", "B"}
    for word in ("ramp", "plan", "rasp", "segment_order", "stopsPassed"):
        assert word not in v


def test_old_positions_are_not_shown(client: TestClient, clock: ManualClock) -> None:
    vehicles(client)  # первый снимок
    clock.advance(6 * 60)  # через 6 минут все отметки старше порога
    response = client.get("/api/v1/live/vehicles")
    assert response.status_code == 200
    assert response.json()["vehicles"] == []


def test_source_down_returns_previous_snapshot(
    client: TestClient, feed: FakeTransitFeed, clock: ManualClock
) -> None:
    first = client.get("/api/v1/live/vehicles").json()
    feed.fail = True
    clock.advance(90)
    second = client.get("/api/v1/live/vehicles").json()
    # Снимок прошлый; часть машин за 90 с могла устареть и пропасть, новых быть не может.
    assert second["diagnostics"]["fetchedAt"] == first["diagnostics"]["fetchedAt"]
    assert second["vehicles"]
    assert {v["id"] for v in second["vehicles"]} <= {v["id"] for v in first["vehicles"]}


def test_source_down_without_snapshot_is_503(client: TestClient, feed: FakeTransitFeed) -> None:
    feed.fail = True
    response = client.get("/api/v1/live/vehicles")
    assert response.status_code == 503
    assert response.json()["code"] == "TRANSIT_UNAVAILABLE"
    assert "Попробуйте" in response.json()["message"]


def test_bbox(client: TestClient) -> None:
    everything = vehicles(client, lowFloorOnly="false")
    north = vehicles(client, lowFloorOnly="false", bbox="55.09,82.9,55.2,83.1")
    assert 0 < len(north) < len(everything)
    assert all(v["point"]["lat"] >= 55.09 for v in north)


@pytest.mark.parametrize("bbox", ["1,2,3", "a,b,c,d", "55.2,82.9,55.0,83.1", "95,0,96,1"])
def test_bad_bbox(client: TestClient, bbox: str) -> None:
    response = client.get("/api/v1/live/vehicles", params={"bbox": bbox})
    assert response.status_code == 422
    assert response.json()["code"] == "BAD_BBOX"


def test_routes_list_with_counts(client: TestClient) -> None:
    body = client.get("/api/v1/live/routes").json()
    by_id = {item["line"]["id"]: item for item in body["lines"]}
    assert by_id["bus-3"]["line"]["number"] == "3"
    assert by_id["bus-3"]["vehiclesOnLine"] > 0
    assert by_id["tram-0013"]["line"]["type"] == "tram"
    assert by_id["bus-005"]["vehiclesOnLine"] == 0  # машин маршрута 5 нет в образце
    off = client.get("/api/v1/live/routes", params={"lowFloorOnly": "false"}).json()
    off_by_id = {item["line"]["id"]: item for item in off["lines"]}
    assert off_by_id["bus-3"]["vehiclesOnLine"] >= by_id["bus-3"]["vehiclesOnLine"]


def test_routes_sorted_and_filtered_by_type(client: TestClient) -> None:
    body = client.get("/api/v1/live/routes", params={"type": "tram"}).json()
    numbers = [item["line"]["number"] for item in body["lines"]]
    assert numbers
    assert {item["line"]["type"] for item in body["lines"]} == {"tram"}
    as_int = [int("".join(c for c in n if c.isdigit())) for n in numbers]
    assert as_int == sorted(as_int)


def test_route_details(client: TestClient) -> None:
    response = client.get("/api/v1/live/routes/bus-3", params={"lowFloorOnly": "false"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["line"]["id"] == "bus-3"
    (direction_a,) = body["directions"]  # в образцах есть только направление A
    assert direction_a["direction"] == "A"
    assert len(direction_a["stops"]) == 35
    assert len(direction_a["path"]) == 335
    assert direction_a["vehicles"]
    for item in direction_a["vehicles"]:
        assert item["vehicle"]["direction"] == "A"
        assert item["nextStopOrder"] is None or 0 < item["nextStopOrder"] < 35


def test_unknown_route_is_404(client: TestClient) -> None:
    response = client.get("/api/v1/live/routes/bus-нет")
    assert response.status_code == 404
    assert response.json() == {"code": "LINE_NOT_FOUND", "message": "Такого маршрута нет."}


def test_hundred_users_one_poll(client: TestClient, feed: FakeTransitFeed) -> None:
    for _ in range(100):
        client.get("/api/v1/live/vehicles")
    polls = feed.vehicle_requests
    lines = len(client.get("/api/v1/live/routes").json()["lines"])
    assert polls == -(-lines // 6)


def test_snapshot_refreshed_after_interval(
    client: TestClient, feed: FakeTransitFeed, clock: ManualClock
) -> None:
    client.get("/api/v1/live/vehicles")
    first = feed.vehicle_requests
    clock.advance(61)
    client.get("/api/v1/live/vehicles")
    assert feed.vehicle_requests == 2 * first
