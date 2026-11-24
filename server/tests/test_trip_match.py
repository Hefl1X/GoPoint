"""Проверки GPS-сопоставления на фиксированных движениях и календаре."""

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.adapters.tsugaet.schedule_parse import parse_route_schedule
from app.domain.gtfs import ServiceWindow
from app.domain.low_floor import TripOccurrence
from app.domain.models import Accessibility, Direction, LiveVehicle, TransportType, VehicleState
from app.domain.schedule import ScheduleRoute, ScheduleStop, reconstruct_trips
from app.domain.schedule_snapshot import CallTime, PublishedTrip, ScheduledService, ScheduleSnapshot
from app.domain.stop_binding import StopBinding
from app.domain.trip_match import (
    DEFAULT_MATCH_SETTINGS,
    MatchStatus,
    MotionState,
    TripMatches,
    TripScheduleIndex,
    match_trips,
)
from tests.test_linear import LAT0, live, straight_path
from tools.build_gtfs import SAMPLES

DAY = date(2026, 11, 23)
WINDOW = ServiceWindow(DAY, DAY + timedelta(days=6))
SIX = 6 * 3600
FIRST = (SIX, SIX + 120, SIX + 240, SIX + 360)
MIDNIGHT = datetime.combine(DAY, time(), ZoneInfo("Asia/Novosibirsk")).astimezone(UTC)


def _service(
    *schedules: tuple[int, ...],
    direction: Direction = Direction.A,
    weekdays: frozenset[int] = frozenset(range(7)),
) -> ScheduledService:
    path = straight_path(len(schedules[0]))
    stops = path.stops
    if direction is Direction.B:
        stops = [
            stop.model_copy(update={"order": i, "point_index": i})
            for i, stop in enumerate(reversed(stops))
        ]
    return ScheduledService(
        f"bus-1-{direction.value}",
        "bus-1",
        direction,
        weekdays,
        WINDOW,
        tuple(
            StopBinding(ScheduleStop(stop.stop.id, i, stop.stop.name), stop)
            for i, stop in enumerate(stops, start=1)
        ),
        tuple(stop.stop.point for stop in stops),
        tuple(
            PublishedTrip(f"{direction.value}-{i}", tuple(CallTime(t, t) for t in times))
            for i, times in enumerate(schedules)
        ),
    )


def _index(*services: ScheduledService, version: str = "fixture") -> TripScheduleIndex:
    return TripScheduleIndex(ScheduleSnapshot(version, WINDOW, services))


def _at(seconds: int) -> datetime:
    return MIDNIGHT + timedelta(seconds=seconds)


def _obs(
    at: int,
    lat_delta: float,
    *,
    vehicle_id: str = "car",
    direction: Direction = Direction.A,
    state: VehicleState = VehicleState.NO_PLAN,
    ramp: Accessibility = Accessibility.YES,
) -> LiveVehicle:
    observation = live(LAT0 + lat_delta, observed=_at(at))
    return observation.model_copy(
        update={
            "on_line": False,
            "state": state,
            "vehicle": observation.vehicle.model_copy(
                update={"id": vehicle_id, "direction": direction, "low_floor": ramp}
            ),
        }
    )


def _step(
    index: TripScheduleIndex, now: int, *vehicles: LiveVehicle, previous: TripMatches | None = None
) -> TripMatches:
    return match_trips(index, {v.vehicle.id: v for v in vehicles}, now=_at(now), previous=previous)


def test_delay_uses_time_nav_and_two_distinct_positions_with_no_vehicle_plan() -> None:
    index = _index(_service(FIRST))
    origin = _obs(SIX + 90, 0.0025)
    before = _step(index, SIX + 110, origin)
    assert before.vehicles["car"].assignment is None
    repeated = _step(index, SIX + 130, origin, previous=before)
    assert repeated == before

    after = _step(index, SIX + 260, _obs(SIX + 210, 0.0075), previous=repeated)
    match = after.vehicles["car"]
    assert match.status is MatchStatus.CONFIRMED
    assert match.motion is MotionState.IN_SERVICE
    assert match.assignment is not None
    assert match.assignment.occurrence == TripOccurrence("A-0", DAY)
    assert match.low_floor_occurrence == match.assignment.occurrence
    assert match.assignment.delay_s == pytest.approx(30)
    assert match.observed_at == _at(SIX + 210)
    assert match.valid_until == _at(SIX + 510)


def test_delay_by_one_headway_leaves_two_equally_supported_trips() -> None:
    later = tuple(t + 600 for t in FIRST)
    index = _index(_service(FIRST, later))
    before = _step(index, SIX + 660, _obs(SIX + 660, 0.0025))
    after = _step(index, SIX + 780, _obs(SIX + 780, 0.0075), previous=before)
    result = after.vehicles["car"]
    assert result.status is MatchStatus.AMBIGUOUS
    assert result.assignment is None
    assert [candidate.delay_s for candidate in result.candidates] == pytest.approx([600, 0])


def test_two_cars_cannot_confirm_the_same_trip_or_displace_an_incumbent() -> None:
    index = _index(_service(FIRST))
    first = tuple(_obs(SIX + 60, 0.0025, vehicle_id=id_) for id_ in ("a", "b"))
    second = tuple(_obs(SIX + 180, 0.0075, vehicle_id=id_) for id_ in ("a", "b"))
    before = _step(index, SIX + 60, *first)
    contested = _step(index, SIX + 180, *second, previous=before)
    assert {match.status for match in contested.vehicles.values()} == {MatchStatus.AMBIGUOUS}
    assert all(match.assignment is None for match in contested.vehicles.values())
    assert _step(index, SIX + 180, *reversed(second), previous=before) == contested

    a_first = _step(index, SIX + 60, first[0])
    incumbent = _step(index, SIX + 180, *second, previous=a_first)
    assert incumbent.vehicles["a"].status is MatchStatus.CONFIRMED
    challenger = _step(index, SIX + 240, _obs(SIX + 240, 0.01, vehicle_id="b"), previous=incumbent)
    assert challenger.vehicles["a"] == incumbent.vehicles["a"]
    assert challenger.vehicles["b"].status is MatchStatus.AMBIGUOUS


def test_missing_polls_ramp_changes_expiry_and_schedule_version() -> None:
    service = _service(FIRST)
    index = _index(service)
    before = _step(index, SIX + 60, _obs(SIX + 60, 0.0025))
    sample = _obs(SIX + 180, 0.0075)
    confirmed = _step(index, SIX + 180, sample, previous=before)
    assert confirmed.vehicles["car"].status is MatchStatus.CONFIRMED
    assert _step(index, SIX + 181, previous=confirmed) == confirmed

    ramp_lost = _obs(SIX + 180, 0.0075, ramp=Accessibility.UNKNOWN)
    removed = _step(index, SIX + 210, ramp_lost, previous=confirmed)
    assert removed.vehicles["car"].low_floor is Accessibility.UNKNOWN
    assert removed.vehicles["car"].low_floor_occurrence is None
    assert removed.vehicles["car"].assignment == confirmed.vehicles["car"].assignment
    assert removed.vehicles["car"].valid_until == confirmed.vehicles["car"].valid_until
    assert _step(index, SIX + 240, sample, previous=removed) == removed
    restored = _step(index, SIX + 240, _obs(SIX + 240, 0.01), previous=removed)
    assert restored.vehicles["car"].low_floor is Accessibility.YES
    assert restored.vehicles["car"].low_floor_occurrence == TripOccurrence("A-0", DAY)

    assert not _step(index, SIX + 480, previous=confirmed).vehicles
    stale = _step(index, SIX + 480, sample, previous=confirmed)
    assert stale.vehicles["car"].status is MatchStatus.STALE
    assert stale.vehicles["car"].assignment is None
    changed = _step(_index(service, version="updated"), SIX + 240, sample, previous=confirmed)
    assert changed.vehicles["car"].assignment is None


def test_terminal_waiting_and_turnaround_do_not_inherit_low_floor() -> None:
    outbound = tuple(t + 480 for t in FIRST)
    index = _index(_service(FIRST), _service(outbound, direction=Direction.B))
    at_origin = _obs(SIX - 600, 0, state=VehicleState.PARKED)
    parked = _step(index, SIX - 600, at_origin)
    assert parked.vehicles["car"].motion is MotionState.WAITING
    assert parked.vehicles["car"].assignment is None
    assert parked.vehicles["car"].candidates[0].delay_s is None
    last_wait = _obs(SIX - 1, 0, state=VehicleState.PARKED)
    waiting = _step(index, SIX - 1, last_wait, previous=parked)
    assert waiting.vehicles["car"].observed_at == _at(SIX - 1)
    assert waiting.vehicles["car"].assignment is None

    moving = _step(index, SIX + 60, _obs(SIX + 60, 0.0025), previous=waiting)
    assert moving.vehicles["car"].status is MatchStatus.CONFIRMED
    approaching = _step(index, SIX + 240, _obs(SIX + 240, 0.01), previous=moving)
    assert approaching.vehicles["car"].status is MatchStatus.CONFIRMED
    arrived = _step(index, SIX + 360, _obs(SIX + 360, 0.015), previous=approaching)
    assert arrived.vehicles["car"].motion is MotionState.FINISHED
    assert arrived.vehicles["car"].assignment is None
    reverse = _step(
        index, SIX + 420, _obs(SIX + 420, 0.015, direction=Direction.B), previous=arrived
    )
    assert reverse.vehicles["car"].motion is MotionState.WAITING
    assert reverse.vehicles["car"].assignment is None
    assert reverse.vehicles["car"].low_floor_occurrence is None


def test_invalid_future_and_implausible_jump_are_ignored() -> None:
    index = _index(_service(FIRST))
    future = _step(index, SIX + 59, _obs(SIX + 60, 0.0025))
    assert future.vehicles["car"].status is MatchStatus.STALE
    before = _step(index, SIX + 60, _obs(SIX + 60, 0.0025))
    jump = _step(index, SIX + 61, _obs(SIX + 61, 0.0075), previous=before)
    assert jump.vehicles["car"].assignment is None


def test_conflicting_replay_and_lunch_remove_confirmation() -> None:
    index = _index(_service(FIRST))
    first = _step(index, SIX + 60, _obs(SIX + 60, 0.0025))
    second = _step(index, SIX + 180, _obs(SIX + 180, 0.0075), previous=first)
    assert second.vehicles["car"].status is MatchStatus.CONFIRMED
    delayed = _step(index, SIX + 210, _obs(SIX + 90, 0.005), previous=second)
    assert delayed == second  # Отметка пришла позже, хотя сделана раньше.

    conflicting = _step(index, SIX + 210, _obs(SIX + 180, 0.0125), previous=second)
    assert conflicting.vehicles["car"].assignment is None
    lunch = _step(
        index, SIX + 240, _obs(SIX + 240, 0.01, state=VehicleState.LUNCH), previous=second
    )
    assert lunch.vehicles["car"].motion is MotionState.OUT_OF_SERVICE
    assert lunch.vehicles["car"].low_floor_occurrence is None


def test_segment_order_zero_preserves_ambiguity_on_a_loop() -> None:
    service = _service(tuple(SIX + i * 120 for i in range(7)))
    points = service.shape[:4] + tuple(reversed(service.shape[:3]))
    bindings = tuple(
        replace(
            binding,
            platform=binding.platform.model_copy(
                update={
                    "stop": binding.platform.stop.model_copy(update={"point": point}),
                }
            ),
        )
        for binding, point in zip(service.bindings, points, strict=True)
    )
    index = _index(replace(service, shape=points, bindings=bindings))
    spot = _obs(SIX + 180, 0.0075).model_copy(update={"stops_passed": 0})
    ambiguous = _step(index, SIX + 180, spot)
    assert ambiguous.vehicles["car"].status is MatchStatus.AMBIGUOUS
    assert not ambiguous.vehicles["car"].candidates

    with_hint = _step(index, SIX + 180, spot.model_copy(update={"stops_passed": 2}))
    (candidate,) = with_hint.vehicles["car"].candidates
    assert candidate.delay_s == pytest.approx(0)
    assert with_hint.vehicles["car"].assignment is None


def test_after_midnight_matches_the_previous_service_date_and_weekday() -> None:
    service = _service((86280, 86520, 86640, 86880), weekdays=frozenset({DAY.weekday()}))
    index = _index(service)
    before = _step(index, 86400, _obs(86400, 0.0025))
    after = _step(index, 86580, _obs(86580, 0.0075), previous=before)
    assignment = after.vehicles["car"].assignment
    assert assignment is not None and assignment.occurrence == TripOccurrence("A-0", DAY)
    assert assignment.delay_s == pytest.approx(0)
    assert not service.operates_on(DAY + timedelta(days=1))


def test_real_tram_times_differ_at_the_same_position_on_a_fixture_line() -> None:
    def read(name: str) -> str:
        return (SAMPLES / name).read_text(encoding="utf-8")

    schedule = parse_route_schedule(
        read("tram13-A-day11-all.html"),
        read("tram13-A-stops.xml"),
        read("tram13-A-days.xml"),
        route=ScheduleRoute(TransportType.TRAM, "0013", "13", Direction.A),
        day_id="11",
    )
    timetable = [
        tuple(call.time for call in trip.calls) for trip in reconstruct_trips(schedule).trips
    ]
    first = timetable[0]
    other = next(t for t in timetable if t[-2] - t[0] != first[-2] - first[0])

    for times in (first, other):
        index = _index(replace(_service(times), weekdays=frozenset(range(5))))
        n = len(times) - 2  # Предпоследняя остановка на синтетической прямой.
        state, ambiguous, candidates = index.candidates(
            _obs(times[n], n * 0.005), DEFAULT_MATCH_SETTINGS
        )
        assert state is MotionState.IN_SERVICE and not ambiguous
        assert len(candidates) == 1 and candidates[0].delay_s == pytest.approx(0)
