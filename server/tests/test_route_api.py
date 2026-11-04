"""POST /api/v1/route и /route/check на образцах ЦУГАЭТ (машины 04.11.2026 12:28).

Пешие участки считает заглушка: по прямой с поправкой 1,3 при 0,8 м/с.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.adapters.fake.feed import FakeTransitFeed
from app.adapters.tsugaet.parse import parse_traces
from app.config import Settings
from app.domain.geo import distance_m
from app.domain.models import Direction, LatLon, Place, WalkLeg
from app.main import create_app
from app.ports import NoAccessibleWalkError
from tests.conftest import SAMPLES, ManualClock

WALK_SPEED = 0.8


class StraightWalker:
    def __init__(self) -> None:
        self.fail_from: LatLon | None = None

    async def walk(self, origin: Place, destination: Place) -> WalkLeg:
        if self.fail_from is not None and origin.point == self.fail_from:
            raise NoAccessibleWalkError("только лестница")
        d = distance_m(origin.point, destination.point) * 1.3
        return WalkLeg(
            origin=origin,
            destination=destination,
            distance_m=round(d),
            duration_s=round(d / WALK_SPEED),
            geometry=[origin.point, destination.point],
        )


def stop_point(direction: Direction, line_id: str, marsh: str, name_part: str) -> LatLon:
    data = json.loads((SAMPLES / f"trasses_batch_{direction.value}.json").read_text("utf-8"))
    path = parse_traces(
        data, [("bus-3", "3"), ("tram-0013", "0013"), ("minibus-24", "24")], direction
    )[line_id]
    stop = next(s.stop for s in path.stops if name_part in s.stop.name)
    return stop.point


def shifted(p: LatLon, metres: float = 30) -> dict[str, float]:
    return {"lat": p.lat + metres / 111_000, "lon": p.lon}


@pytest.fixture
def walker() -> StraightWalker:
    return StraightWalker()


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def client(walker: StraightWalker, clock: ManualClock) -> TestClient:
    app = create_app(
        Settings(transit_feed="fake", access_stops=4),
        feed=FakeTransitFeed(SAMPLES),
        walk_planner=walker,
        clock=clock,
        start_poller=False,
    )
    return TestClient(app)


# Автобус 3 в сторону Северной короны: от «Библиотеки им. Лермонтова» до конечной.
ORIGIN = stop_point(Direction.A, "bus-3", "3", "Лермонтова")
DEST = stop_point(Direction.A, "bus-3", "3", "Северная корона")


def route(client: TestClient, low_floor_only: bool, **extra: Any) -> dict[str, Any]:
    body = {
        "origin": shifted(ORIGIN, 40),
        "destination": shifted(DEST, -40),
        "lowFloorOnly": low_floor_only,
        **extra,
    }
    response = client.post("/api/v1/route", json=body)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def transit_legs(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [leg for j in body["journeys"] for leg in j["legs"] if leg["kind"] == "transit"]


def test_route_found_with_breakdown(client: TestClient) -> None:
    body = route(client, True)
    assert body["status"] == "ok"
    assert 1 <= len(body["journeys"]) <= 3
    best = body["journeys"][0]
    kinds = [leg["kind"] for leg in best["legs"]]
    assert kinds[0] == "walk"
    assert kinds[-1] == "walk"
    assert "transit" in kinds
    leg = next(leg for leg in best["legs"] if leg["kind"] == "transit")
    assert leg["line"]["number"] == "3"
    assert leg["waitS"] >= 0
    assert leg["departAt"] < leg["arriveAt"]
    # Служебное: способ расчёта есть в ответе, но для логов и тестов.
    assert leg["diagnostics"]["method"] in {"planned", "distance"}
    assert best["arriveAt"] > best["departAt"]


def test_low_floor_only_has_only_yes(client: TestClient) -> None:
    legs = transit_legs(route(client, True))
    assert legs
    assert {leg["lowFloor"] for leg in legs} == {"yes"}


def test_any_transport_marks_low_floor(client: TestClient) -> None:
    legs = transit_legs(route(client, False))
    assert legs
    assert all(leg["lowFloor"] in {"yes", "no", "unknown"} for leg in legs)


def test_any_transport_considers_vehicles_without_low_floor(client: TestClient) -> None:
    # Трамвай 13 в направлении A: есть машины «не низкий пол» (tram-0013-12).
    origin = stop_point(Direction.A, "tram-0013", "0013", "Октябрьский рынок")
    dest = stop_point(Direction.A, "tram-0013", "0013", "Писарева")
    body = {"origin": shifted(origin, 20), "destination": shifted(dest, 20), "lowFloorOnly": True}
    strict = transit_legs(client.post("/api/v1/route", json=body).json())
    assert strict
    assert all(leg["lowFloor"] == "yes" for leg in strict)
    # Без настройки «Низкопольный транспорт» машина без низкого пола может прийти раньше.
    body["lowFloorOnly"] = False
    relaxed = client.post("/api/v1/route", json=body).json()
    assert (
        relaxed["journeys"][0]["arriveAt"]
        <= client.post("/api/v1/route", json={**body, "lowFloorOnly": True}).json()["journeys"][0][
            "arriveAt"
        ]
    )


def test_tram_13_is_not_bus_13(client: TestClient) -> None:
    origin = stop_point(Direction.A, "tram-0013", "0013", "Октябрьский рынок")
    dest = stop_point(Direction.A, "tram-0013", "0013", "Писарева")
    body = {"origin": shifted(origin, 20), "destination": shifted(dest, 20), "lowFloorOnly": False}
    legs = transit_legs(client.post("/api/v1/route", json=body).json())
    assert legs
    assert {leg["line"]["id"] for leg in legs} == {"tram-0013"}
    assert {leg["line"]["type"] for leg in legs} == {"tram"}


def test_no_fresh_vehicles_means_no_transit(client: TestClient, clock: ManualClock) -> None:
    clock.advance(3600)  # все отметки старше 5 минут: свежих машин нет
    body = route(client, True)
    assert body["status"] == "no_transit"
    assert body["journeys"] == []
    assert body["message"] == "Транспорта сейчас нет"


def test_no_suitable_vehicle(client: TestClient) -> None:
    # Обратно (к началу линии направления A) машин A нет, а B рядом не ходит так.
    body = route(client, True, origin=shifted(DEST, -40), destination=shifted(ORIGIN, 40))
    if body["status"] == "no_transit":
        assert body["journeys"] == []
        assert body["message"] == "Транспорта сейчас нет"


def test_outside_city(client: TestClient) -> None:
    response = client.post(
        "/api/v1/route",
        json={"origin": {"lat": 56.5, "lon": 84.9}, "destination": shifted(DEST)},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "OUTSIDE_CITY"


def test_origin_only_reachable_by_stairs(client: TestClient, walker: StraightWalker) -> None:
    origin = shifted(ORIGIN, 40)
    walker.fail_from = LatLon(lat=origin["lat"], lon=origin["lon"])
    response = client.post(
        "/api/v1/route", json={"origin": origin, "destination": shifted(DEST, -40)}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "NO_ACCESSIBLE_WALK"


def test_source_down_uses_previous_snapshot(client: TestClient) -> None:
    route(client, True)
    feed: FakeTransitFeed = client.app.state.live._feed  # type: ignore[attr-defined]  # тест
    feed.fail = True
    assert route(client, True)["status"] == "ok"


# --- пересчёт ---


def check(client: TestClient, vehicle_id: str, planned: str) -> dict[str, Any]:
    body = {
        "origin": shifted(ORIGIN, 40),
        "destination": shifted(DEST, -40),
        "lowFloorOnly": True,
        "vehicleId": vehicle_id,
        "plannedArriveAt": planned,
    }
    response = client.post("/api/v1/route/check", json=body)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def first_vehicle(journey: dict[str, Any]) -> str:
    leg = next(leg for leg in journey["legs"] if leg["kind"] == "transit")
    vehicle_id: str = leg["vehicleId"]
    return vehicle_id


def test_check_ok_when_on_plan(client: TestClient) -> None:
    best = route(client, True)["journeys"][0]
    result = check(client, first_vehicle(best), best["arriveAt"])
    assert result["status"] == "ok"
    assert result["alternative"] is None
    assert result["current"]["arriveAt"] == best["arriveAt"]


def test_check_gone_vehicle_offers_alternative_without_replacing(client: TestClient) -> None:
    body = route(client, True)
    best = body["journeys"][0]
    result = check(client, "bus-3-999", best["arriveAt"])
    assert result["status"] == "gone"
    assert result["current"] is None
    if len(body["journeys"]) > 0:
        assert result["alternative"] is not None


def test_check_stopped_vehicle(client: TestClient, clock: ManualClock) -> None:
    best = route(client, True)["journeys"][0]
    vehicle_id = first_vehicle(best)
    live = client.app.state.live  # type: ignore[attr-defined]  # тест
    clock.advance(10)
    # Машина «стоит» с момента отметки больше 5 минут: подменяем её историю.
    still = live._still[vehicle_id]  # тест: внутреннее состояние
    live._still[vehicle_id] = type(still)(
        point=still.point, since=still.since - timedelta(minutes=7)
    )
    result = check(client, vehicle_id, best["arriveAt"])
    assert result["status"] == "stopped"
    assert result["stoppedForS"] >= 420
