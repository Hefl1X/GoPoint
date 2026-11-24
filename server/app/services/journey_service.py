"""Поиск в OTP и проверка допустимости посадок по текущему состоянию."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.geo import distance_m
from app.domain.low_floor import LowFloorSnapshot, TripOccurrence, allows_low_floor
from app.domain.models import Place, VariantLabel, WalkLeg
from app.domain.trip_plan import (
    CheckedRide,
    JourneyCheck,
    JourneyChoices,
    JourneyOption,
    JourneySelection,
    PlannedJourney,
    PlannedWalk,
    RoutingGraph,
    TripPlan,
    TripSegment,
    TripTimetable,
)
from app.ports import TransitPlanner, TransitPlannerUnavailableError, WalkPlanner, WalkPlannerError
from app.services.live_snapshot import Clock

# Эти ответы OTP совместимы с полностью выполненным поиском.
_SEARCH_RESULTS = frozenset(
    {
        "NO_DIRECT_MODE_CONNECTION",
        "NO_STOPS_IN_RANGE",
        "NO_TRANSIT_CONNECTION",
        "NO_TRANSIT_CONNECTION_IN_SEARCH_WINDOW",
        "WALKING_BETTER_THAN_TRANSIT",
    }
)


@dataclass(frozen=True)
class JourneySettings:
    walk_limit_m: float
    board_slack_s: int
    transfer_slack_s: int


def _walking_seconds(journey: PlannedJourney) -> int:
    return sum(step.leg.duration_s for step in journey.legs if isinstance(step, PlannedWalk))


def _options(journeys: list[PlannedJourney]) -> tuple[JourneyOption, ...]:
    # Один вариант на цепочку рейсов с конкретными позициями посадки и высадки.
    unique: dict[tuple[TripSegment, ...], PlannedJourney] = {}
    for journey in sorted(journeys, key=lambda item: item.arrive_at):
        unique.setdefault(tuple(ride.segment for ride in journey.rides), journey)
    ordered = list(unique.values())
    indices = range(len(ordered))
    winners: tuple[tuple[VariantLabel, int], ...] = (
        ("fastest", 0),
        ("fewest_transfers", min(indices, key=lambda i: len(ordered[i].rides))),
        ("least_walking", min(indices, key=lambda i: _walking_seconds(ordered[i]))),
    )
    ranked: dict[int, list[VariantLabel]] = {}
    for label, winner in winners:
        ranked.setdefault(winner, []).append(label)
    for i in range(min(3, len(ordered))):
        if len(ranked) == 3:
            break
        ranked.setdefault(i, [])
    return tuple(JourneyOption(ordered[i], tuple(ranked[i])) for i in sorted(ranked))


class JourneyService:
    def __init__(
        self,
        planner: TransitPlanner,
        walking: WalkPlanner,
        *,
        clock: Clock,
        low_floor: Callable[[], LowFloorSnapshot | None],
        settings: JourneySettings,
    ) -> None:
        self._planner = planner
        self._walking = walking
        self._clock = clock
        self._low_floor = low_floor
        self._s = settings

    async def plan(
        self,
        origin: Place,
        destination: Place,
        *,
        graph: RoutingGraph | None,
        low_floor_only: bool,
    ) -> JourneyChoices:
        at = self._clock()
        before = self._low_floor() if low_floor_only else None
        try:
            result = await self._planner.plan(
                origin, destination, at=at, low_floor_only=low_floor_only
            )
        except TransitPlannerUnavailableError:
            walk = await self._walk(origin, destination, None)
            return JourneyChoices("transit_unavailable", None, walk=walk)
        walk = await self._walk(origin, destination, result)
        version = result.graph_version
        if graph is None or version != graph.version or result.routing_errors - _SEARCH_RESULTS:
            return JourneyChoices("transit_unavailable", None, walk=walk)
        now = self._clock()
        current = self._low_floor() if low_floor_only else None
        if low_floor_only and (
            current is None
            or before is not current
            or current.graph_version != version
            or now >= current.valid_until
        ):
            return JourneyChoices("transit_unavailable", version, walk=walk)

        rides = [journey for journey in result.journeys if journey.rides]
        eligible = [
            journey
            for journey in rides
            if not low_floor_only
            or allows_low_floor(
                tuple(ride.segment.occurrence for ride in journey.rides),
                otp_version=version,
                requested=before,
                current=current,
                now=now,
            )
        ]
        if not eligible:
            return JourneyChoices(
                "transit_unavailable" if rides or not graph.complete_coverage else "no_transit",
                version,
                walk=walk,
            )
        if walk is not None:
            walk_arrives = at + timedelta(seconds=walk.duration_s)
            eligible = [
                journey
                for journey in eligible
                if journey.arrive_at < walk_arrives and _walking_seconds(journey) < walk.duration_s
            ]
            if not eligible:
                return JourneyChoices("walk_better", version, walk=walk)
        return JourneyChoices("ok", version, _options(eligible), walk)

    async def _walk(
        self, origin: Place, destination: Place, result: TripPlan | None
    ) -> WalkLeg | None:
        if result is not None:
            direct = [
                leg.leg
                for journey in result.journeys
                if len(journey.legs) == 1 and isinstance(leg := journey.legs[0], PlannedWalk)
            ]
            if direct:
                shortest = min(direct, key=lambda item: item.distance_m)
                if shortest.distance_m > self._s.walk_limit_m:
                    return None
                return shortest.model_copy(update={"origin": origin, "destination": destination})
        if distance_m(origin.point, destination.point) > self._s.walk_limit_m:
            return None
        try:
            walk = await self._walking.walk(origin, destination)
        except WalkPlannerError:
            return None
        return walk if walk.distance_m <= self._s.walk_limit_m else None

    async def check(
        self,
        selection: JourneySelection,
        *,
        graph: RoutingGraph | None,
        low_floor_only: bool,
        ready_at: datetime,
    ) -> JourneyCheck:
        if graph is None:
            return JourneyCheck("transit_unavailable")
        if selection.graph_version != graph.version or not selection.rides:
            return JourneyCheck("changed")
        before = self._low_floor() if low_floor_only else None
        occurrences = tuple(dict.fromkeys(ride.segment.occurrence for ride in selection.rides))
        try:
            lookups = await asyncio.gather(
                *(
                    self._planner.timetable(trip, low_floor_only=low_floor_only)
                    for trip in occurrences
                )
            )
        except TransitPlannerUnavailableError:
            return JourneyCheck("transit_unavailable")
        if any(item.graph_version != graph.version for item in lookups):
            return JourneyCheck("transit_unavailable")
        now = self._clock()
        if low_floor_only and not allows_low_floor(
            occurrences,
            otp_version=graph.version,
            requested=before,
            current=self._low_floor(),
            now=now,
        ):
            return JourneyCheck("transit_unavailable")
        timetables = {
            occurrence: result.timetable
            for occurrence, result in zip(occurrences, lookups, strict=True)
        }
        return self._check_connections(selection, timetables, max(now, ready_at))

    def _check_connections(
        self,
        selection: JourneySelection,
        timetables: dict[TripOccurrence, TripTimetable | None],
        ready: datetime,
    ) -> JourneyCheck:
        checked: list[CheckedRide] = []
        for selected in selection.rides:
            segment = selected.segment
            trip = timetables[segment.occurrence]
            board, alight = segment.board_sequence, segment.alight_sequence
            if (
                trip is None
                or trip.canceled
                or not (1 <= board < alight <= len(trip.calls))
                or selected.walk_before_s < 0
            ):
                return JourneyCheck("changed")
            first, last = trip.calls[board - 1], trip.calls[alight - 1]
            depart_at, arrive_at = first.depart_at, last.arrive_at
            slack = self._s.board_slack_s + (self._s.transfer_slack_s if checked else 0)
            earliest = ready + timedelta(seconds=slack + selected.walk_before_s)
            if (
                depart_at is None
                or arrive_at is None
                or depart_at < earliest
                or arrive_at < depart_at
            ):
                return JourneyCheck("changed")
            checked.append(
                CheckedRide(
                    segment,
                    depart_at,
                    arrive_at,
                    "realtime"
                    if "realtime" in (first.time_source, last.time_source)
                    else "scheduled",
                )
            )
            ready = arrive_at
        return JourneyCheck("ok", tuple(checked))
