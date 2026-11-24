"""Публичный контракт OTP через обычный create_app на фиксированных ответах."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.adapters.fake.feed import FakeTransitFeed
from app.config import Settings
from app.domain.gtfs import ServiceWindow
from app.domain.schedule_snapshot import ScheduleSnapshot
from app.domain.trip_plan import PlannedJourney, TripLookup, TripPlan
from app.main import create_app
from tests.conftest import SAMPLES, ManualClock
from tests.test_journey_service import (
    CHAIN,
    DAY,
    FIRST,
    GRAPH,
    NOW,
    SECOND,
    A,
    B,
    _Planner,
    _Walker,
)

POINTS = {"origin": A.point.model_dump(), "destination": B.point.model_dump()}


@pytest.fixture
def planner() -> _Planner:
    return _Planner(TripPlan(GRAPH.version, (PlannedJourney((FIRST,)),), frozenset()))


@pytest.fixture
def feed() -> FakeTransitFeed:
    source = FakeTransitFeed(SAMPLES)
    source.fail = True
    return source


@pytest.fixture
def client(planner: _Planner, feed: FakeTransitFeed) -> Iterator[TestClient]:
    app = create_app(
        Settings(),
        feed=feed,
        walk_planner=_Walker(),
        transit_planner=planner,
        clock=ManualClock(NOW),
        start_poller=False,
        realtime_schedule=ScheduleSnapshot(GRAPH.version, ServiceWindow(DAY, DAY), ()),
    )
    with TestClient(app) as result:
        yield result


def test_general_route_returns_a_scheduled_bus_during_cold_gps_failure(
    client: TestClient, feed: FakeTransitFeed
) -> None:
    response = client.post("/api/v1/route", json={**POINTS, "lowFloorOnly": False})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["graphVersion"] == GRAPH.version
    assert data["diagnostics"] is None
    (journey,) = data["journeys"]
    (ride,) = journey["legs"]
    assert ride["tripId"] == FIRST.segment.occurrence.trip_id
    assert ride["serviceDate"] == DAY.isoformat()
    assert ride["boardSequence"] == 1 and ride["alightSequence"] == 2
    assert ride["timeSource"] == "scheduled" and ride["lowFloor"] == "unknown"
    assert ride["vehicleId"] is ride["stopsAway"] is ride["diagnostics"] is None
    assert ride["waitS"] == 60
    assert data["walk"] is not None
    assert feed.vehicle_requests == 0


def test_default_low_mode_rejects_the_unconfirmed_ride(client: TestClient) -> None:
    data = client.post("/api/v1/route", json=POINTS).json()
    assert data["status"] == "transit_unavailable"
    assert data["journeys"] == []
    assert data["walk"] is not None


def test_short_walk_survives_cold_otp_and_gps_failure(
    client: TestClient, planner: _Planner, feed: FakeTransitFeed
) -> None:
    planner.result = None
    data = client.post("/api/v1/route", json=POINTS).json()
    assert data["status"] == "transit_unavailable"
    assert data["walk"]["distanceM"] == 200
    assert data["diagnostics"] is None
    assert feed.vehicle_requests == 0


def _selected() -> dict[str, Any]:
    return {
        "graphVersion": GRAPH.version,
        "readyAt": NOW.isoformat(),
        "lowFloorOnly": False,
        "rides": [
            {
                "tripId": ride.segment.occurrence.trip_id,
                "serviceDate": DAY.isoformat(),
                "boardSequence": ride.segment.board_sequence,
                "alightSequence": ride.segment.alight_sequence,
                "walkBeforeS": 0,
            }
            for ride in CHAIN.rides
        ],
    }


def test_check_updates_every_leg_and_detects_a_changed_second_ride(
    client: TestClient, planner: _Planner
) -> None:
    body = _selected()
    response = client.post("/api/v1/route/check", json=body)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert [ride["tripId"] for ride in payload["rides"]] == [
        ride["tripId"] for ride in body["rides"]
    ]
    assert payload["rides"][1]["serviceDate"] == DAY.isoformat()
    planner.lookups[SECOND.segment.occurrence] = TripLookup(GRAPH.version, None)
    assert client.post("/api/v1/route/check", json=body).json() == {
        "status": "changed",
        "rides": [],
    }
    assert planner.plan_calls == 0


def test_check_rejects_a_new_graph_and_reversed_sequences(
    client: TestClient, planner: _Planner
) -> None:
    body = _selected()
    assert client.post("/api/v1/route/check", json={**body, "graphVersion": "old"}).json() == {
        "status": "changed",
        "rides": [],
    }
    body["rides"][0]["boardSequence"] = 2
    assert client.post("/api/v1/route/check", json=body).status_code == 422
    assert planner.queried == []
