"""Сопоставление GPS с рейсами принятого расписания, без ввода-вывода."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from zoneinfo import ZoneInfo

from app.domain.geo import distance_m
from app.domain.linear import LineGeometry, build_geometry, projection_candidates, stops_passed
from app.domain.low_floor import TripOccurrence
from app.domain.models import Accessibility, Direction, LatLon, LinePath, LiveVehicle, VehicleState
from app.domain.schedule_snapshot import PublishedTrip, ScheduledService, ScheduleSnapshot

_LOCAL = ZoneInfo("Asia/Novosibirsk")
_DAY_S = 86_400
_STOP_EPS_M = 1.0


class MatchStatus(StrEnum):
    CONFIRMED = "confirmed"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"
    STALE = "stale"


class MotionState(StrEnum):
    UNKNOWN = "unknown"
    WAITING = "waiting"
    IN_SERVICE = "in_service"
    FINISHED = "finished"
    TURNAROUND = "turnaround"
    OUT_OF_SERVICE = "out_of_service"


@dataclass(frozen=True)
class MatchSettings:
    stale_s: int = 300
    future_tolerance_s: int = 0
    early_s: int = 120
    late_s: int = 1800
    terminal_wait_s: int = 1800
    max_offset_m: float = 200
    terminal_radius_m: float = 35
    min_progress_m: float = 35
    delay_change_s: float = 120
    max_speed_mps: float = 30


DEFAULT_MATCH_SETTINGS = MatchSettings()


@dataclass(frozen=True)
class TripCandidate:
    occurrence: TripOccurrence
    along_m: float
    delay_s: float | None


@dataclass(frozen=True)
class VehicleMatch:
    observed_at: datetime
    valid_until: datetime
    line_id: str
    direction: Direction
    point: LatLon
    low_floor: Accessibility
    motion: MotionState
    status: MatchStatus
    candidates: tuple[TripCandidate, ...] = ()
    assignment: TripCandidate | None = None
    turnaround_until: datetime | None = None

    @property
    def low_floor_occurrence(self) -> TripOccurrence | None:
        if self.status is MatchStatus.CONFIRMED and self.low_floor is Accessibility.YES:
            return self.assignment.occurrence if self.assignment is not None else None
        return None


@dataclass(frozen=True)
class TripMatches:
    version: str
    vehicles: Mapping[str, VehicleMatch]

    def __post_init__(self) -> None:
        object.__setattr__(self, "vehicles", MappingProxyType(dict(self.vehicles)))


@dataclass(frozen=True)
class _IndexedService:
    service: ScheduledService
    geometry: LineGeometry
    trips: tuple[PublishedTrip, ...]
    departures: tuple[int, ...]
    max_duration_s: int
    latest_s: int


def _index(service: ScheduledService) -> _IndexedService:
    geometry = build_geometry(
        LinePath(
            line_id=service.line_id,
            direction=service.direction,
            points=list(service.shape),
            stops=[binding.platform for binding in service.bindings],
        )
    )
    trips = tuple(sorted(service.trips, key=lambda trip: trip.stop_times[0].departure))
    departures = tuple(trip.stop_times[0].departure for trip in trips)
    return _IndexedService(
        service,
        geometry,
        trips,
        departures,
        max(
            trip.stop_times[-1].arrival - departure
            for trip, departure in zip(trips, departures, strict=True)
        ),
        max(trip.stop_times[-1].arrival for trip in trips),
    )


class TripScheduleIndex:
    """Геометрия и отсортированные отправления для каждого направления."""

    def __init__(self, snapshot: ScheduleSnapshot) -> None:
        self.version = snapshot.version
        services: dict[tuple[str, Direction], list[_IndexedService]] = defaultdict(list)
        for service in snapshot.services:
            if service.trips:
                services[service.line_id, service.direction].append(_index(service))
        self._services = {key: tuple(values) for key, values in services.items()}

    def candidates(
        self, live: LiveVehicle, settings: MatchSettings
    ) -> tuple[MotionState, bool, tuple[TripCandidate, ...]]:
        """Состояние, неоднозначность геометрии и рейсы в допустимом окне."""
        if live.state is VehicleState.LUNCH:
            return MotionState.OUT_OF_SERVICE, False, ()
        vehicle = live.vehicle
        entries = self._services.get((vehicle.line_id, vehicle.direction), ())
        local = vehicle.position_observed_at.astimezone(_LOCAL)
        phases: set[MotionState] = set()
        candidates: list[TripCandidate] = []
        for entry in entries:
            phase, ambiguous, along_m = _position(entry.geometry, live, settings)
            if ambiguous:
                return MotionState.UNKNOWN, True, ()
            if phase is not MotionState.UNKNOWN:
                phases.add(phase)
            if along_m is not None:
                candidates.extend(_candidates(entry, phase, along_m, local, settings))
        if len(phases) > 1:
            return MotionState.UNKNOWN, True, ()
        return next(iter(phases), MotionState.UNKNOWN), False, tuple(candidates)

    def receding(self, before: VehicleMatch, after: VehicleMatch, settings: MatchSettings) -> bool:
        """Свежая пара точек уверенно уходит назад вдоль прежнего направления."""
        entries = self._services.get((after.line_id, after.direction), ())
        elapsed_s = (after.observed_at - before.observed_at).total_seconds()
        for entry in entries:
            points = [
                projection_candidates(
                    entry.geometry, item.point, max_offset_m=settings.max_offset_m
                )
                for item in (before, after)
            ]
            if any(len(options) != 1 for options in points):
                return False
            backwards_m = points[0][0].along_m - points[1][0].along_m
            if not settings.min_progress_m <= backwards_m <= elapsed_s * settings.max_speed_mps:
                return False
        return bool(entries)


def _position(
    geometry: LineGeometry, live: LiveVehicle, settings: MatchSettings
) -> tuple[MotionState, bool, float | None]:
    point = live.vehicle.point
    options = projection_candidates(geometry, point, max_offset_m=settings.max_offset_m)
    if len(options) > 1 and live.stops_passed:
        agreeing = tuple(
            option
            for option in options
            if abs(stops_passed(geometry, option.along_m) - live.stops_passed) <= 1
        )
        options = agreeing or options
    if len(options) != 1:
        return MotionState.UNKNOWN, bool(options), None

    along_m = options[0].along_m
    first, last = geometry.stop_along_m[0], geometry.stop_along_m[-1]
    stops = geometry.path.stops
    if along_m >= last - _STOP_EPS_M:
        return MotionState.FINISHED, False, None
    if along_m < first + settings.terminal_radius_m and (
        distance_m(point, stops[0].stop.point) <= settings.terminal_radius_m
    ):
        return MotionState.WAITING, False, first
    if live.state is VehicleState.PARKED:
        return MotionState.OUT_OF_SERVICE, False, None
    if along_m < first:
        return MotionState.UNKNOWN, False, None
    return MotionState.IN_SERVICE, False, along_m


def _plan_time(trip: PublishedTrip, stops: list[float], along_m: float, elapsed_s: float) -> float:
    right = bisect_left(stops, along_m)
    call = trip.stop_times[right]
    if along_m == stops[right]:
        return min(max(elapsed_s, call.arrival), call.departure)
    left = right - 1
    depart = trip.stop_times[left].departure
    fraction = (along_m - stops[left]) / (stops[right] - stops[left])
    return depart + (call.arrival - depart) * fraction


def _candidates(
    entry: _IndexedService,
    phase: MotionState,
    along_m: float,
    at: datetime,
    settings: MatchSettings,
) -> list[TripCandidate]:
    waiting = phase is MotionState.WAITING
    early_s = settings.terminal_wait_s if waiting else settings.early_s
    local_s = (at - at.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
    earliest_day = int((local_s - entry.latest_s - settings.late_s) // _DAY_S)
    latest_day = int((local_s + early_s) // _DAY_S)
    result: list[TripCandidate] = []
    for offset in range(earliest_day, latest_day + 1):
        day = at.date() + timedelta(days=offset)
        if not entry.service.operates_on(day):
            continue
        elapsed = local_s - offset * _DAY_S
        max_duration = 0 if waiting else entry.max_duration_s
        first = bisect_left(entry.departures, elapsed - settings.late_s - max_duration)
        last = bisect_right(entry.departures, elapsed + early_s)
        for trip in entry.trips[first:last]:
            plan = (
                trip.stop_times[0].departure
                if waiting
                else _plan_time(trip, entry.geometry.stop_along_m, along_m, elapsed)
            )
            delay = elapsed - plan
            if -early_s <= delay <= settings.late_s:
                occurrence = TripOccurrence(trip.trip_id, day)
                result.append(TripCandidate(occurrence, along_m, None if waiting else delay))
    return result


def _consistent(
    before: TripCandidate, after: TripCandidate, elapsed_s: float, settings: MatchSettings
) -> bool:
    progress = after.along_m - before.along_m
    if (
        not -settings.min_progress_m
        <= progress
        <= elapsed_s * settings.max_speed_mps + settings.min_progress_m
    ):
        return False
    return (
        before.delay_s is None
        or after.delay_s is None
        or abs(after.delay_s - before.delay_s) <= settings.delay_change_s
    )


def _assignment(
    current: VehicleMatch, previous: VehicleMatch, settings: MatchSettings
) -> TripCandidate | None:
    elapsed = (current.observed_at - previous.observed_at).total_seconds()
    candidates = {item.occurrence: item for item in current.candidates}
    if previous.assignment is not None:
        before = previous.assignment
        after = candidates.get(before.occurrence)
        return (
            after if after is not None and _consistent(before, after, elapsed, settings) else None
        )
    if current.motion is not MotionState.IN_SERVICE:
        return None
    supported: list[TripCandidate] = []
    for before in previous.candidates:
        after = candidates.get(before.occurrence)
        if after is not None and (
            after.along_m - before.along_m >= settings.min_progress_m
            and _consistent(before, after, elapsed, settings)
        ):
            supported.append(after)
    return supported[0] if len(supported) == 1 else None


def _replayed(current: VehicleMatch, previous: VehicleMatch, state: VehicleState) -> VehicleMatch:
    if current.observed_at < previous.observed_at:
        return previous
    if current.line_id != previous.line_id or current.direction is not previous.direction:
        return current
    if (
        current.point != previous.point
        or state is VehicleState.LUNCH
        or (state is VehicleState.PARKED and previous.motion is MotionState.IN_SERVICE)
    ):
        return replace(current, turnaround_until=previous.turnaround_until)
    accessibility = (
        previous.low_floor if current.low_floor is Accessibility.YES else current.low_floor
    )
    return replace(previous, low_floor=accessibility)


def _observe(
    index: TripScheduleIndex,
    live: LiveVehicle,
    previous: VehicleMatch | None,
    now: datetime,
    settings: MatchSettings,
) -> VehicleMatch:
    vehicle = live.vehicle
    at = vehicle.position_observed_at
    valid_until = at + timedelta(seconds=settings.stale_s)
    current = VehicleMatch(
        at,
        valid_until,
        vehicle.line_id,
        vehicle.direction,
        vehicle.point,
        vehicle.low_floor,
        MotionState.UNKNOWN,
        MatchStatus.UNMATCHED,
    )
    if (
        at.utcoffset() is None
        or now >= valid_until
        or at > now + timedelta(seconds=settings.future_tolerance_s)
    ):
        return previous or replace(current, status=MatchStatus.STALE)
    if previous is not None and at <= previous.observed_at:
        return _replayed(current, previous, live.state)

    motion, geometry_ambiguous, candidates = index.candidates(live, settings)
    ambiguous = geometry_ambiguous or len(candidates) > 1
    current = replace(
        current,
        motion=motion,
        candidates=candidates,
        status=MatchStatus.AMBIGUOUS if ambiguous else MatchStatus.UNMATCHED,
        turnaround_until=valid_until if motion is MotionState.FINISHED else None,
    )
    if (
        previous is None
        or previous.line_id != current.line_id
        or previous.direction is not current.direction
    ):
        return current
    # Источник может ещё сообщать старое направление, когда машина уходит с конечной.
    until = previous.turnaround_until
    if (
        previous.motion is MotionState.TURNAROUND
        and motion is MotionState.IN_SERVICE
        and index.receding(previous, current, settings)
    ):
        until = valid_until
    if (
        until is not None
        and now < until
        and motion not in {MotionState.WAITING, MotionState.FINISHED}
    ):
        inside_old_direction = motion is MotionState.IN_SERVICE
        return replace(
            current,
            motion=MotionState.TURNAROUND if inside_old_direction else motion,
            status=MatchStatus.UNMATCHED if inside_old_direction else current.status,
            candidates=(),
            turnaround_until=until,
        )
    assignment = _assignment(current, previous, settings)
    if assignment is None:
        return current
    return replace(current, assignment=assignment, status=MatchStatus.CONFIRMED)


def _resolve_conflicts(
    results: dict[str, VehicleMatch], previous: Mapping[str, VehicleMatch]
) -> None:
    by_trip: dict[TripOccurrence, list[str]] = defaultdict(list)
    for vehicle_id, match in results.items():
        if match.assignment is not None:
            by_trip[match.assignment.occurrence].append(vehicle_id)

    for trip, vehicles in by_trip.items():
        if len(vehicles) == 1:
            continue
        incumbents = [
            vehicle_id
            for vehicle_id in vehicles
            if (old := previous.get(vehicle_id)) is not None
            and old.assignment is not None
            and old.assignment.occurrence == trip
        ]
        keeper = incumbents[0] if len(incumbents) == 1 else None
        for vehicle_id in vehicles:
            if vehicle_id != keeper:
                results[vehicle_id] = replace(
                    results[vehicle_id], assignment=None, status=MatchStatus.AMBIGUOUS
                )


def match_trips(
    index: TripScheduleIndex,
    vehicles: Mapping[str, LiveVehicle],
    *,
    now: datetime,
    previous: TripMatches | None = None,
    settings: MatchSettings = DEFAULT_MATCH_SETTINGS,
) -> TripMatches:
    """Обрабатывает один снимок по ID, сохраняя память только до срока GPS-свидетельства."""
    if now.utcoffset() is None:
        raise ValueError("Часы matcher должны содержать часовой пояс")
    history: dict[str, VehicleMatch] = {}
    if previous is not None and previous.version == index.version:
        history = {
            vehicle_id: match
            for vehicle_id, match in previous.vehicles.items()
            if match.status is not MatchStatus.STALE
            and match.observed_at <= now + timedelta(seconds=settings.future_tolerance_s)
            and now < match.valid_until
        }
    results = dict(history)
    for vehicle_id, observation in vehicles.items():
        results[vehicle_id] = _observe(index, observation, history.get(vehicle_id), now, settings)
    _resolve_conflicts(results, history)
    return TripMatches(index.version, results)
