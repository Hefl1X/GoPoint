"""Пешие участки: кэш и адрес POST /api/v1/walk (без сети)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.models import LatLon, Place, WalkLeg
from app.main import create_app
from app.ports import (
    NoAccessibleWalkError,
    NoWalkRouteError,
    PointNotOnStreetError,
    WalkPlannerError,
    WalkPlannerUnavailableError,
)
from app.services.walking import WalkingService
from tests.conftest import ManualClock


class StubPlanner:
    def __init__(self) -> None:
        self.calls = 0
        self.error: WalkPlannerError | None = None

    async def walk(self, origin: Place, destination: Place) -> WalkLeg:
        self.calls += 1
        if self.error:
            raise self.error
        return WalkLeg(
            origin=origin,
            destination=destination,
            distance_m=420,
            duration_s=600,
            geometry=[origin.point, destination.point],
            climb_m=2.0,
            descent_m=0.5,
        )


A = Place(point=LatLon(lat=55.03, lon=82.92))
B = Place(point=LatLon(lat=55.04, lon=82.93))


async def test_same_pair_is_cached_with_own_labels() -> None:
    planner = StubPlanner()
    service = WalkingService(planner)
    await service.walk(A, B)
    near_a = Place(name="Дом", point=LatLon(lat=55.03002, lon=82.92001))
    leg = await service.walk(near_a, B)
    assert planner.calls == 1
    assert leg.origin.name == "Дом"


async def test_errors_are_not_cached() -> None:
    planner = StubPlanner()
    planner.error = WalkPlannerUnavailableError("нет")
    service = WalkingService(planner)
    with pytest.raises(WalkPlannerUnavailableError):
        await service.walk(A, B)
    planner.error = None
    await service.walk(A, B)
    assert planner.calls == 2


@pytest.fixture
def planner() -> StubPlanner:
    return StubPlanner()


@pytest.fixture
def client(planner: StubPlanner) -> TestClient:
    app = create_app(
        Settings(transit_feed="fake"), walk_planner=planner, clock=ManualClock(), start_poller=False
    )
    return TestClient(app)


BODY = {"origin": {"lat": 55.03, "lon": 82.92}, "destination": {"lat": 55.04, "lon": 82.93}}


def test_api_walk(client: TestClient) -> None:
    response = client.post("/api/v1/walk", json=BODY)
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "walk"
    assert body["durationS"] == 600
    assert body["distanceM"] == 420
    assert body["geometry"][0] == {"lat": 55.03, "lon": 82.92}
    assert body["climbM"] == 2.0


def test_api_walk_outside_city(client: TestClient, planner: StubPlanner) -> None:
    body = {**BODY, "destination": {"lat": 56.5, "lon": 84.9}}
    response = client.post("/api/v1/walk", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "OUTSIDE_CITY"
    assert planner.calls == 0


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (PointNotOnStreetError("x"), 422, "POINT_NOT_ON_STREET"),
        (NoWalkRouteError("x"), 422, "NO_WALK_ROUTE"),
        (NoAccessibleWalkError("x"), 422, "NO_ACCESSIBLE_WALK"),
        (WalkPlannerUnavailableError("x"), 503, "WALK_UNAVAILABLE"),
    ],
)
def test_api_walk_errors_in_russian(
    client: TestClient, planner: StubPlanner, error: WalkPlannerError, status: int, code: str
) -> None:
    planner.error = error
    response = client.post("/api/v1/walk", json=BODY)
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert any("а" <= ch <= "я" for ch in body["message"])
    assert "55.03" not in response.text
