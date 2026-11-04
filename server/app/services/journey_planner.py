"""Маршрут «сейчас»: машины на линии + пешие участки + поиск (раздел 8 ARCHITECTURE).

Собирает данные из сервиса снимка (машины, линии) и сервиса пеших участков (OTP),
строит рейсы машин (domain/linear.py), ищет варианты (domain/journey_search.py) и
превращает их в шаги для экрана. Пешие пересадки в поиске оцениваются по прямой,
а в готовом варианте пересчитываются по улицам; если с настоящим временем пересадка
не успевает, вариант отбрасывается. Координаты в журнал не пишутся.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.domain.geo import distance_m
from app.domain.journey_search import Plan, Ride, SearchParams, TransferWalk, Trip, search
from app.domain.linear import EtaParams, LineGeometry, build_geometry, locate, stop_calls
from app.domain.live import usable_vehicles
from app.domain.models import (
    Direction,
    EtaDiagnostics,
    Journey,
    LatLon,
    Leg,
    Line,
    LinePath,
    LiveVehicle,
    Place,
    Stop,
    TransitLeg,
    WalkLeg,
)
from app.ports import (
    NoAccessibleWalkError,
    PointNotOnStreetError,
    TransitFeedError,
    WalkPlannerError,
)
from app.services.live_snapshot import Clock, LiveSnapshotService, Snapshot
from app.services.walking import WalkingService

log = logging.getLogger(__name__)

# Пешая пересадка по прямой короче, чем по улицам: множитель для оценки в поиске.
TRANSFER_DETOUR = 1.4
# Насколько дальше горизонта посадки смотреть время прихода на остановки (длинные поездки).
RIDE_EXTRA = timedelta(minutes=90)
# Сколько пеших запросов к OTP одновременно.
WALK_CONCURRENCY = 4


class TransitUnavailableError(Exception):
    """Нет ни свежего, ни годного прошлого снимка машин."""


@dataclass(frozen=True)
class PlannerSettings:
    eta: EtaParams
    search: SearchParams
    stale_seconds: int
    max_vehicle_offset_m: float
    transfer_radius_m: float
    access_stops: int
    horizon: timedelta
    walk_speed_mps: float
    snapshot_max_age: timedelta


@dataclass(frozen=True)
class RouteOutcome:
    journeys: list[Journey]
    status: Literal["ok", "no_transit"]
    snapshot: Snapshot


CheckStatus = Literal["ok", "stopped", "late", "gone"]
# Новый вариант предлагаем, только если он быстрее хотя бы на столько.
MIN_GAIN = timedelta(minutes=1)


@dataclass(frozen=True)
class CheckOutcome:
    """Проверка выбранного маршрута: что с машиной и есть ли вариант лучше."""

    status: CheckStatus
    stopped_for_s: int | None
    current: Journey | None  # тот же маршрут с новым временем (None, если машину уже не догнать)
    alternative: Journey | None  # предложение; сам маршрут не заменяется
    gain_s: int | None  # насколько раньше приедет по предложению
    snapshot: Snapshot


@dataclass(frozen=True)
class _Context:
    """Всё, что нужно, чтобы превратить найденный вариант в шаги."""

    now: datetime
    origin: LatLon
    destination: LatLon
    access: dict[str, WalkLeg]
    egress: dict[str, WalkLeg]
    trips: dict[str, tuple[Trip, LiveVehicle]]
    lines: dict[str, Line]
    low_floor_only: bool


@dataclass
class _Network:
    """Линии, остановки и пешие пересадки (пересчитываются, когда меняются линии)."""

    source: dict[tuple[str, Direction], LinePath]
    geometry: dict[tuple[str, Direction], LineGeometry]
    stops: dict[str, Stop]
    transfers: dict[str, list[tuple[str, int]]]


class JourneyPlanner:
    def __init__(
        self,
        live: LiveSnapshotService,
        walking: WalkingService,
        *,
        clock: Clock,
        settings: PlannerSettings,
    ) -> None:
        self._live = live
        self._walking = walking
        self._clock = clock
        self._s = settings
        self._network: _Network | None = None

    @property
    def settings(self) -> PlannerSettings:
        return self._s

    # ------------------------------------------------------------ данные

    async def _snapshot(self) -> Snapshot:
        try:
            snap = await self._live.snapshot()
        except TransitFeedError as exc:
            raise TransitUnavailableError(str(exc)) from exc
        if self._clock() - snap.fetched_at > self._s.snapshot_max_age:
            raise TransitUnavailableError("последний снимок слишком старый")
        return snap

    async def _load_network(self) -> _Network:
        try:
            source = await self._live.network()
        except TransitFeedError as exc:
            raise TransitUnavailableError(str(exc)) from exc
        if self._network is not None and self._network.source is source:
            return self._network
        geometry = {key: build_geometry(path) for key, path in source.items()}
        stops: dict[str, Stop] = {}
        for path in source.values():
            for rs in path.stops:
                stops.setdefault(rs.stop.id, rs.stop)
        self._network = _Network(source, geometry, stops, self._transfers(stops))
        return self._network

    def _transfers(self, stops: dict[str, Stop]) -> dict[str, list[tuple[str, int]]]:
        """Соседние остановки в радиусе пересадки; время по прямой с поправкой на улицы."""
        radius = self._s.transfer_radius_m
        if radius <= 0:
            return {}
        # Сетка ~radius, чтобы не сравнивать все пары остановок.
        cell = radius / 111_000
        grid: dict[tuple[int, int], list[Stop]] = {}
        for stop in stops.values():
            key = (math.floor(stop.point.lat / cell), math.floor(stop.point.lon / cell))
            grid.setdefault(key, []).append(stop)
        result: dict[str, list[tuple[str, int]]] = {}
        for (gx, gy), group in grid.items():
            near = [
                s
                for dx in (-1, 0, 1)
                for dy in (-2, -1, 0, 1, 2)
                for s in grid.get((gx + dx, gy + dy), [])
            ]
            for a in group:
                for b in near:
                    if a.id == b.id:
                        continue
                    d = distance_m(a.point, b.point)
                    if d <= radius:
                        seconds = round(d * TRANSFER_DETOUR / self._s.walk_speed_mps)
                        result.setdefault(a.id, []).append((b.id, seconds))
        return result

    def _trips(
        self,
        network: _Network,
        snap: Snapshot,
        now: datetime,
        low_floor_only: bool,
        ring_lines: frozenset[str],
    ) -> dict[str, tuple[Trip, LiveVehicle]]:
        usable = {
            v.id for v in usable_vehicles(snap.vehicles, now, self._s.stale_seconds, low_floor_only)
        }
        trips: dict[str, tuple[Trip, LiveVehicle]] = {}
        # Сесть нужно в пределах горизонта, а ехать можно дольше: остановки берём с запасом.
        horizon = now + self._s.horizon + RIDE_EXTRA
        for live in snap.vehicles:
            v = live.vehicle
            if v.id not in usable:
                continue
            geom = network.geometry.get((v.line_id, v.direction))
            if geom is None:
                continue  # у маршрута нет линии в этом направлении
            proj = locate(
                geom,
                v.point,
                max_offset_m=self._s.max_vehicle_offset_m,
                segment_order=live.stops_passed,
            )
            if proj is None:
                continue  # машина в стороне от линии: не на маршруте
            calls = stop_calls(
                geom,
                proj,
                live,
                now=now,
                horizon=horizon,
                params=self._s.eta,
                ring=v.line_id in ring_lines,
            )
            if len(calls) >= 2:
                trips[v.id] = (Trip(v.id, calls), live)
        return trips

    async def _walks(
        self, network: _Network, point: LatLon, *, to_point: bool
    ) -> tuple[dict[str, WalkLeg], list[WalkPlannerError]]:
        """Пешком от точки до ближайших остановок (или от них до точки)."""
        nearest = sorted(network.stops.values(), key=lambda s: distance_m(s.point, point))
        chosen = nearest[: self._s.access_stops]
        here = Place(point=point)
        sem = asyncio.Semaphore(WALK_CONCURRENCY)

        async def one(stop: Stop) -> WalkLeg:
            place = Place(name=stop.name, point=stop.point)
            async with sem:
                if to_point:
                    return await self._walking.walk(place, here)
                return await self._walking.walk(here, place)

        results = await asyncio.gather(*(one(s) for s in chosen), return_exceptions=True)
        legs: dict[str, WalkLeg] = {}
        errors: list[WalkPlannerError] = []
        for stop, result in zip(chosen, results, strict=True):
            if isinstance(result, WalkLeg):
                legs[stop.id] = result
            elif isinstance(result, WalkPlannerError):
                errors.append(result)
            elif isinstance(result, BaseException):
                raise result
        return legs, errors

    # ------------------------------------------------------------ расчёт

    async def plan(
        self,
        origin: LatLon,
        destination: LatLon,
        *,
        low_floor_only: bool,
        exclude: frozenset[str] = frozenset(),
        first_vehicle: str | None = None,
    ) -> RouteOutcome:
        snap = await self._snapshot()
        network = await self._load_network()
        lines = {line.id: line for line in await self._live.lines()}
        ring_lines = frozenset(i for i, line in lines.items() if line.ring)
        now = self._clock()

        (access, a_err), (egress, b_err) = await asyncio.gather(
            self._walks(network, origin, to_point=False),
            self._walks(network, destination, to_point=True),
        )
        for legs, errors in ((access, a_err), (egress, b_err)):
            if not legs and errors:
                raise _most_telling(errors)

        trips = self._trips(network, snap, now, low_floor_only, ring_lines)
        usable_trips = [t for vid, (t, _) in trips.items() if vid not in exclude]
        plans = search(
            now,
            usable_trips,
            {sid: leg.duration_s for sid, leg in access.items()},
            {sid: leg.duration_s for sid, leg in egress.items()},
            network.transfers,
            self._s.search,
            first_vehicle=first_vehicle,
        )
        ctx = _Context(now, origin, destination, access, egress, trips, lines, low_floor_only)
        journeys: list[Journey] = []
        for plan in plans:
            journey = await self._journey(plan, ctx)
            if journey is not None:
                journeys.append(journey)
        return RouteOutcome(journeys, "ok" if journeys else "no_transit", snap)

    async def check(
        self,
        origin: LatLon,
        destination: LatLon,
        *,
        low_floor_only: bool,
        vehicle_id: str,
        planned_arrive_at: datetime,
        stopped_threshold: timedelta,
        late_threshold: timedelta,
    ) -> CheckOutcome:
        """Пересчёт: если выбранная машина стоит, пропала или опаздывает, предложить вариант.

        Маршрут человека не меняется: сервер только сообщает, насколько изменится время.
        """
        now = self._clock()
        current_outcome = await self.plan(
            origin, destination, low_floor_only=low_floor_only, first_vehicle=vehicle_id
        )
        snap = current_outcome.snapshot
        current = current_outcome.journeys[0] if current_outcome.journeys else None
        still = self._live.still_for(vehicle_id, now)
        on_line = any(
            v.id == vehicle_id
            for v in usable_vehicles(snap.vehicles, now, self._s.stale_seconds, low_floor_only)
        )
        status: CheckStatus
        if not on_line or current is None:
            status = "gone"
        elif still is not None and still > stopped_threshold:
            status = "stopped"
        elif current.arrive_at > planned_arrive_at + late_threshold:
            status = "late"
        else:
            status = "ok"

        alternative: Journey | None = None
        gain: timedelta | None = None
        if status != "ok":
            other = await self.plan(
                origin,
                destination,
                low_floor_only=low_floor_only,
                exclude=frozenset({vehicle_id}),
            )
            best = other.journeys[0] if other.journeys else None
            if best is not None:
                gain = (current.arrive_at - best.arrive_at) if current else None
                if gain is None or gain >= MIN_GAIN:
                    alternative = best
        return CheckOutcome(
            status=status,
            stopped_for_s=round(still.total_seconds()) if still is not None else None,
            current=current,
            alternative=alternative,
            gain_s=round(gain.total_seconds()) if gain is not None and alternative else None,
            snapshot=snap,
        )

    async def _journey(self, plan: Plan, ctx: _Context) -> Journey | None:
        """Шаги варианта с настоящими пешими участками. None, если пересадка не успевает."""
        trips = ctx.trips
        first = ctx.access[plan.access_stop]
        legs: list[Leg] = [first.model_copy(update={"origin": Place(point=ctx.origin)})]
        ready = ctx.now + timedelta(seconds=first.duration_s)
        margin = timedelta(seconds=self._s.search.board_margin_s)
        transfer_margin = timedelta(seconds=self._s.search.transfer_margin_s)
        rides = 0
        for step in plan.steps:
            if isinstance(step, TransferWalk):
                a = self._stop(step.from_stop, plan, trips)
                b = self._stop(step.to_stop, plan, trips)
                try:
                    walk = await self._walking.walk(
                        Place(name=a.name, point=a.point), Place(name=b.name, point=b.point)
                    )
                except WalkPlannerError:
                    return None  # на пересадке нет доступного пути
                legs.append(walk)
                ready += timedelta(seconds=walk.duration_s)
                continue
            leg = self._transit_leg(step, trips, ctx.lines, ready)
            needed = margin + (transfer_margin if rides else timedelta())
            if ready + needed > leg.depart_at:
                return None
            legs.append(leg)
            ready = leg.arrive_at
            rides += 1
        last = ctx.egress[plan.egress_stop]
        legs.append(last.model_copy(update={"destination": Place(point=ctx.destination)}))
        arrive = ready + timedelta(seconds=last.duration_s)
        return Journey(
            legs=legs,
            depart_at=ctx.now,
            arrive_at=arrive,
            duration_s=round((arrive - ctx.now).total_seconds()),
            transfers=max(0, rides - 1),
            low_floor_only=ctx.low_floor_only,
        )

    @staticmethod
    def _stop(stop_id: str, plan: Plan, trips: dict[str, tuple[Trip, LiveVehicle]]) -> Stop:
        for ride in plan.rides:
            for call in ride.trip.calls:
                if call.stop.id == stop_id:
                    return call.stop
        raise KeyError(stop_id)

    @staticmethod
    def _transit_leg(
        ride: Ride,
        trips: dict[str, tuple[Trip, LiveVehicle]],
        lines: dict[str, Line],
        ready: datetime,
    ) -> TransitLeg:
        _, live = trips[ride.trip.vehicle_id]
        v = live.vehicle
        board = ride.trip.calls[ride.board]
        alight = ride.trip.calls[ride.alight]
        line = lines.get(v.line_id) or Line(id=v.line_id, type=v.type, number=v.number, title="")
        return TransitLeg(
            vehicle_id=v.id,
            line=line,
            low_floor=v.low_floor,
            board_stop=board.stop,
            alight_stop=alight.stop,
            wait_s=max(0, round((board.arrive_at - ready).total_seconds())),
            depart_at=board.arrive_at,
            arrive_at=alight.arrive_at,
            diagnostics=EtaDiagnostics(
                method=board.method, position_observed_at=v.position_observed_at
            ),
        )


def _most_telling(errors: list[WalkPlannerError]) -> WalkPlannerError:
    """Какую ошибку показать человеку, если ни до одной остановки не дойти."""
    for kind in (PointNotOnStreetError, NoAccessibleWalkError):
        for e in errors:
            if isinstance(e, kind):
                return e
    return errors[0]
