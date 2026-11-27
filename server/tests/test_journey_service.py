"""Допуск всех посадок и проверка выбранной цепочки через порт OTP."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from app.domain.low_floor import LowFloorSnapshot, TripOccurrence
from app.domain.models import LatLon, Line, Place, Stop, TransportType, WalkLeg
from app.domain.trip_plan import (
    JourneySelection,
    PlannedJourney,
    PlannedRide,
    PlannedWalk,
    RoutingGraph,
    SelectedRide,
    TimetabledCall,
    TripLookup,
    TripPlan,
    TripSegment,
    TripTimetable,
)
from app.ports import TransitPlannerUnavailableError, WalkPlannerUnavailableError
from app.services.journey_service import JourneyService, JourneySettings
from tests.conftest import ManualClock

NOW = datetime.fromisoformat("2026-11-24T23:54:00+07:00")
DAY = date(2026, 11, 24)
GRAPH = RoutingGraph("graph", True)
PARTIAL = RoutingGraph("graph", False)
A = Place(name="А", point=LatLon(lat=55.0, lon=83.0))
B = Place(name="Б", point=LatLon(lat=55.001, lon=83.001))
BOARD = Stop(id="1", name="Посадка", point=A.point)
ALIGHT = Stop(id="2", name="Выход", point=B.point)
LINE = Line(id="bus-8", type=TransportType.BUS, title="Автобус 8", number="8")


def _at(minutes: int) -> datetime:
    return NOW + timedelta(minutes=minutes)


def _ride(trip: str, depart: int, arrive: int) -> PlannedRide:
    return PlannedRide(
        TripSegment(TripOccurrence(trip, DAY), 1, 2),
        LINE,
        BOARD,
        ALIGHT,
        _at(depart),
        _at(arrive),
        "scheduled",
        None,
        (),
    )


FIRST = _ride("first", 1, 8)
SECOND = _ride("second", 11, 16)
THIRD = _ride("third", 19, 24)
CHAIN = PlannedJourney((FIRST, SECOND, THIRD))


def _snapshot(*confirmed: PlannedRide) -> LowFloorSnapshot:
    expires = _at(5)
    return LowFloorSnapshot(
        GRAPH.version, expires, {ride.segment.occurrence: expires for ride in confirmed}
    )


def _timetable(ride: PlannedRide) -> TripLookup:
    return TripLookup(
        GRAPH.version,
        TripTimetable(
            ride.segment.occurrence,
            (
                TimetabledCall(BOARD.id, ride.depart_at, ride.depart_at, ride.time_source),
                TimetabledCall(ALIGHT.id, ride.arrive_at, ride.arrive_at, ride.time_source),
            ),
            False,
        ),
    )


class _Planner:
    result: TripPlan | None

    def __init__(self, result: TripPlan | None = None) -> None:
        self.result = result
        self.lookups = {
            ride.segment.occurrence: _timetable(ride) for ride in (FIRST, SECOND, THIRD)
        }
        self.queried: list[TripOccurrence] = []
        self.plan_calls = 0
        self.on_plan: Callable[[], None] = lambda: None

    async def plan(
        self, origin: Place, destination: Place, *, at: datetime, low_floor_only: bool
    ) -> TripPlan:
        self.plan_calls += 1
        self.on_plan()
        if self.result is None:
            raise TransitPlannerUnavailableError
        return self.result

    async def timetable(self, occurrence: TripOccurrence, *, low_floor_only: bool) -> TripLookup:
        self.queried.append(occurrence)
        return self.lookups[occurrence]


class _Walker:
    distance_m = 200
    duration_s = 30 * 60
    available = True

    async def walk(self, origin: Place, destination: Place) -> WalkLeg:
        if not self.available:
            raise WalkPlannerUnavailableError
        return WalkLeg(
            origin=origin,
            destination=destination,
            distance_m=self.distance_m,
            duration_s=self.duration_s,
        )


def _service(
    planner: _Planner,
    low_floor: Callable[[], LowFloorSnapshot | None],
    clock: ManualClock | None = None,
) -> JourneyService:
    return JourneyService(
        planner,
        _Walker(),
        clock=clock or ManualClock(NOW),
        low_floor=low_floor,
        settings=JourneySettings(walk_limit_m=2000, board_slack_s=30, transfer_slack_s=60),
    )


async def test_general_plan_needs_no_live_snapshot_for_scheduled_trip() -> None:
    def no_gps_access() -> None:
        pytest.fail("Общий поиск запросил GPS")

    planner = _Planner(TripPlan(GRAPH.version, (PlannedJourney((FIRST,)),), frozenset()))
    result = await _service(planner, no_gps_access).plan(A, B, graph=PARTIAL, low_floor_only=False)
    assert result.status == "ok" and result.graph_version == GRAPH.version
    assert result.options[0].journey.rides == (FIRST,)
    assert result.walk is not None and result.walk.distance_m == 200


async def test_missing_third_confirmation_blocks_low_floor_chain() -> None:
    planner = _Planner(TripPlan(GRAPH.version, (CHAIN,), frozenset()))
    snapshot = _snapshot(FIRST, SECOND, THIRD)
    service = _service(planner, lambda: snapshot)
    result = await service.plan(A, B, graph=GRAPH, low_floor_only=True)
    assert result.status == "ok" and result.options[0].journey.rides == CHAIN.rides
    snapshot = _snapshot(FIRST, SECOND)
    result = await service.plan(A, B, graph=GRAPH, low_floor_only=True)
    assert result.status == "transit_unavailable" and not result.options and result.walk


@pytest.mark.parametrize("event", ["expiration", "replacement", "mismatch"])
async def test_low_floor_revalidates_state_after_planning(event: str) -> None:
    clock = ManualClock(NOW)
    snapshot = _snapshot(FIRST, SECOND, THIRD)
    unexpected_version = "old" if event == "mismatch" else GRAPH.version
    planner = _Planner(TripPlan(unexpected_version, (CHAIN,), frozenset()))

    def changed() -> None:
        nonlocal snapshot
        if event == "expiration":
            clock.advance(5 * 60)
        elif event == "replacement":
            snapshot = _snapshot(FIRST, SECOND, THIRD)

    planner.on_plan = changed
    result = await _service(planner, lambda: snapshot, clock).plan(
        A, B, graph=GRAPH, low_floor_only=True
    )
    assert result.status == "transit_unavailable" and not result.options


async def test_search_reports_unavailable_when_graph_is_partial_expired_or_offline() -> None:
    empty = TripPlan(GRAPH.version, (), frozenset({"NO_TRANSIT_CONNECTION"}))
    service = _service(_Planner(empty), lambda: None)
    assert (await service.plan(A, B, graph=GRAPH, low_floor_only=False)).status == "no_transit"
    partial = await service.plan(A, B, graph=PARTIAL, low_floor_only=False)
    assert partial.status == "transit_unavailable" and partial.walk
    expired = replace(empty, routing_errors=frozenset({"OUTSIDE_SERVICE_PERIOD"}))
    for result in (expired, None):
        response = await _service(_Planner(result), lambda: None).plan(
            A, B, graph=GRAPH, low_floor_only=False
        )
        assert response.status == "transit_unavailable" and response.walk


@pytest.mark.parametrize(("walk_s", "status"), [(600, "ok"), (480, "walk_better")])
async def test_transit_must_beat_direct_walking(walk_s: int, status: str) -> None:
    short_access = PlannedWalk(
        WalkLeg(origin=A, destination=A, distance_m=50, duration_s=30),
        NOW,
        NOW + timedelta(seconds=30),
    )
    long_access = PlannedWalk(
        WalkLeg(origin=A, destination=A, distance_m=600, duration_s=1800), NOW, _at(30)
    )
    short_ride = PlannedJourney((short_access, FIRST))
    long_ride = PlannedJourney((long_access, replace(FIRST, depart_at=_at(31), arrive_at=_at(36))))
    walk = PlannedWalk(
        WalkLeg(origin=A, destination=B, distance_m=200, duration_s=walk_s), NOW, _at(walk_s // 60)
    )
    planner = _Planner(
        TripPlan(GRAPH.version, (short_ride, long_ride, PlannedJourney((walk,))), frozenset())
    )
    result = await _service(planner, lambda: None).plan(A, B, graph=GRAPH, low_floor_only=False)
    assert result.status == status
    assert result.walk == walk.leg
    assert tuple(option.journey for option in result.options) == (
        (short_ride,) if status == "ok" else ()
    )


@pytest.mark.parametrize("second_ride_changed", [False, True])
async def test_check_uses_every_selected_ride_and_keeps_exact_identities(
    second_ride_changed: bool,
) -> None:
    planner = _Planner()
    second_id = SECOND.segment.occurrence
    if second_ride_changed:
        planner.lookups[second_id] = TripLookup(GRAPH.version, None)
    selection = JourneySelection(
        GRAPH.version,
        tuple(SelectedRide(ride.segment, 40 if ride is SECOND else 0) for ride in CHAIN.rides),
    )
    response = await _service(planner, lambda: None).check(
        selection, graph=GRAPH, low_floor_only=False, ready_at=NOW
    )
    assert planner.plan_calls == 0
    assert planner.queried == [ride.segment.occurrence for ride in CHAIN.rides]
    assert response.status == ("changed" if second_ride_changed else "ok")
    if not second_ride_changed:
        assert tuple(ride.segment for ride in response.rides) == tuple(
            ride.segment for ride in CHAIN.rides
        )


async def test_check_rejects_a_transfer_missed_after_delay() -> None:
    planner = _Planner()
    planner.lookups[FIRST.segment.occurrence] = _timetable(
        replace(FIRST, arrive_at=_at(10), time_source="realtime")
    )
    selection = JourneySelection(
        GRAPH.version, tuple(SelectedRide(ride.segment, 0) for ride in CHAIN.rides)
    )
    response = await _service(planner, lambda: None).check(
        selection, graph=GRAPH, low_floor_only=False, ready_at=NOW
    )
    assert response.status == "changed" and not response.rides
