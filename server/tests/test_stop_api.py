"""GET /api/v1/live/stops/{id}/arrivals и /live/vehicles/{id} на образцах ЦУГАЭТ."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.adapters.fake.feed import FakeTransitFeed
from app.adapters.tsugaet.parse import parse_traces
from app.config import Settings
from app.domain.models import Direction, Stop
from app.main import create_app
from tests.conftest import SAMPLES, ManualClock
from tests.test_route_api import StraightWalker


def bus3_stops(direction: Direction) -> list[Stop]:
    data = json.loads((SAMPLES / f"trasses_batch_{direction.value}.json").read_text("utf-8"))
    path = parse_traces(
        data, [("bus-3", "3"), ("tram-0013", "0013"), ("minibus-24", "24")], direction
    )["bus-3"]
    return [s.stop for s in path.stops]


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def client(clock: ManualClock) -> TestClient:
    app = create_app(
        Settings(transit_feed="fake"),
        feed=FakeTransitFeed(SAMPLES),
        walk_planner=StraightWalker(),
        clock=clock,
        start_poller=False,
    )
    return TestClient(app)


def arrivals(client: TestClient, stop_id: str, low_floor_only: bool) -> dict[str, Any]:
    response = client.get(
        f"/api/v1/live/stops/{stop_id}/arrivals",
        params={"lowFloorOnly": str(low_floor_only).lower()},
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def busiest_stop(client: TestClient) -> tuple[str, dict[str, Any]]:
    """Остановка автобуса 3, к которой подъезжает больше всего машин (любых)."""
    best: tuple[str, dict[str, Any]] | None = None
    for stop in bus3_stops(Direction.A)[1:-1]:
        body = arrivals(client, stop.id, False)
        if best is None or len(body["arrivals"]) > len(best[1]["arrivals"]):
            best = (stop.id, body)
    assert best is not None
    return best


def test_stop_arrivals_sorted_with_heading(client: TestClient, clock: ManualClock) -> None:
    stop_id, body = busiest_stop(client)
    assert body["stop"]["id"] == stop_id
    items = body["arrivals"]
    assert items, "к остановкам автобуса 3 в образце подъезжают машины"
    times = [datetime.fromisoformat(a["arriveAt"]) for a in items]
    assert times == sorted(times)
    for item in items:
        assert datetime.fromisoformat(item["arriveAt"]) >= clock.now
        assert item["stopsAway"] >= 0
        assert item["diagnostics"]["method"] in {"planned", "distance"}
    bus3 = [a for a in items if a["vehicle"]["lineId"] == "bus-3"]
    for item in bus3:
        if item["vehicle"]["direction"] == "A":
            assert "Северная корона" in item["toward"]


def test_stop_arrivals_at_most_two_per_line_direction(client: TestClient) -> None:
    _, body = busiest_stop(client)
    seen: dict[tuple[str, str], int] = {}
    for item in body["arrivals"]:
        key = (item["vehicle"]["lineId"], item["vehicle"]["direction"])
        seen[key] = seen.get(key, 0) + 1
    assert max(seen.values()) <= 2


def test_stop_arrivals_low_floor_only(client: TestClient) -> None:
    stop_id, any_body = busiest_stop(client)
    low = arrivals(client, stop_id, True)
    assert {a["vehicle"]["lowFloor"] for a in low["arrivals"]} <= {"yes"}
    assert len(low["arrivals"]) <= len(any_body["arrivals"])


def test_unknown_stop_is_404_in_russian(client: TestClient) -> None:
    response = client.get("/api/v1/live/stops/no-such-stop/arrivals")
    assert response.status_code == 404
    assert response.json()["code"] == "STOP_NOT_FOUND"
    assert response.json()["message"] == "Такой остановки нет."


def test_stale_positions_do_not_arrive(client: TestClient, clock: ManualClock) -> None:
    stop_id, _ = busiest_stop(client)
    clock.advance(3600)  # все положения в образце старше 5 минут
    assert arrivals(client, stop_id, False)["arrivals"] == []


def test_vehicle_details_next_stops_in_order(client: TestClient, clock: ManualClock) -> None:
    vehicles = client.get("/api/v1/live/vehicles", params={"lowFloorOnly": "false"}).json()
    bus = next(v for v in vehicles["vehicles"] if v["lineId"] == "bus-3")
    response = client.get(f"/api/v1/live/vehicles/{bus['id']}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vehicle"]["id"] == bus["id"]
    times = [datetime.fromisoformat(s["arriveAt"]) for s in body["nextStops"]]
    assert times == sorted(times)
    assert all(t >= clock.now for t in times)
    assert len(body["nextStops"]) <= 8
    assert body["toward"]


def test_vehicle_not_on_line_is_404(client: TestClient, clock: ManualClock) -> None:
    response = client.get("/api/v1/live/vehicles/no-such-vehicle")
    assert response.status_code == 404
    assert response.json()["code"] == "VEHICLE_NOT_FOUND"
