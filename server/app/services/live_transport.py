"""Карточки машин, остановки и прибытия по общему GPS-снимку."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.linear import EtaParams, LineGeometry, StopCall, build_geometry, locate, stop_calls
from app.domain.live import usable_vehicles
from app.domain.models import (
    Bounds,
    Direction,
    EtaDiagnostics,
    Line,
    LinePath,
    LiveVehicle,
    NextStop,
    Stop,
    StopArrival,
    Vehicle,
)
from app.ports import TransitFeedError
from app.services.live_snapshot import Clock, LiveSnapshotService, Snapshot

# Запас горизонта для дальних остановок уже начатой поездки или для карточки.
RIDE_EXTRA = timedelta(minutes=90)


class TransitUnavailableError(Exception):
    """Нет свежего снимка GPS или данных о сети."""


@dataclass(frozen=True)
class LiveTransportSettings:
    eta: EtaParams
    stale_seconds: int
    max_vehicle_offset_m: float
    horizon: timedelta
    snapshot_max_age: timedelta


@dataclass(frozen=True)
class ArrivalsOutcome:
    stop: Stop | None  # None: такой остановки нет ни на одном маршруте
    arrivals: list[StopArrival]
    snapshot: Snapshot


@dataclass(frozen=True)
class VehicleOutcome:
    vehicle: Vehicle | None  # None: машины нет на линии (или положение устарело)
    toward: str | None
    next_stops: list[NextStop]
    snapshot: Snapshot


# Сколько ближайших машин одного маршрута и направления показывать на остановке.
ARRIVALS_PER_LINE = 2
# Сколько остановок впереди показывать в карточке машины.
VEHICLE_NEXT_STOPS = 8


@dataclass(frozen=True)
class LiveNetwork:
    source: dict[tuple[str, Direction], LinePath]
    geometry: dict[tuple[str, Direction], LineGeometry]
    stops: dict[str, Stop]

    def toward(self, v: Vehicle, lines: dict[str, Line]) -> str | None:
        """Конечная направления, куда едет машина. У кольцевых конечной нет."""
        line = lines.get(v.line_id)
        if line is not None and line.ring:
            return None
        geom = self.geometry.get((v.line_id, v.direction))
        if geom is None or not geom.path.stops:
            return None
        return geom.path.stops[-1].stop.name


class LiveTransportService:
    def __init__(
        self, live: LiveSnapshotService, *, clock: Clock, settings: LiveTransportSettings
    ) -> None:
        self._live = live
        self._clock = clock
        self._s = settings
        self._network: LiveNetwork | None = None

    def visible_vehicles(
        self, snap: Snapshot, now: datetime, low_floor_only: bool
    ) -> list[Vehicle]:
        return usable_vehicles(snap.vehicles, now, self._s.stale_seconds, low_floor_only)

    def still_for(self, vehicle_id: str, now: datetime) -> timedelta | None:
        return self._live.still_for(vehicle_id, now)

    async def snapshot(self) -> Snapshot:
        try:
            snap = await self._live.snapshot()
        except TransitFeedError as exc:
            raise TransitUnavailableError(str(exc)) from exc
        if self._clock() - snap.fetched_at > self._s.snapshot_max_age:
            raise TransitUnavailableError("последний снимок слишком старый")
        return snap

    async def network(self) -> LiveNetwork:
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
        self._network = LiveNetwork(source, geometry, stops)
        return self._network

    def vehicle_calls(
        self,
        network: LiveNetwork,
        snap: Snapshot,
        now: datetime,
        low_floor_only: bool,
        ring_lines: frozenset[str],
        horizon: datetime,
    ) -> dict[str, tuple[list[StopCall], LiveVehicle]]:
        """Машины на линии и время их прихода на остановки впереди (до horizon)."""
        usable = {v.id for v in self.visible_vehicles(snap, now, low_floor_only)}
        result: dict[str, tuple[list[StopCall], LiveVehicle]] = {}
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
            result[v.id] = (calls, live)
        return result

    async def stops_in(self, bounds: Bounds) -> list[Stop]:
        """Остановки всех маршрутов в области карты (без повторов, по названию)."""
        network = await self.network()
        found = [s for s in network.stops.values() if bounds.contains(s.point)]
        return sorted(found, key=lambda s: (s.name, s.id))

    async def stop_arrivals(self, stop_id: str, *, low_floor_only: bool) -> ArrivalsOutcome:
        """Что подъезжает к остановке в пределах горизонта, по времени прихода.

        От каждого маршрута и направления не больше ARRIVALS_PER_LINE ближайших машин.
        """
        snap = await self.snapshot()
        network = await self.network()
        stop = network.stops.get(stop_id)
        if stop is None:
            return ArrivalsOutcome(None, [], snap)
        lines = await self.lines()
        ring_lines = frozenset(i for i, line in lines.items() if line.ring)
        now = self._clock()
        found: list[StopArrival] = []
        for calls, live in self.vehicle_calls(
            network, snap, now, low_floor_only, ring_lines, now + self._s.horizon
        ).values():
            for away, call in enumerate(calls):
                if call.stop.id != stop_id:
                    continue
                v = live.vehicle
                found.append(
                    StopArrival(
                        vehicle=v,
                        toward=network.toward(v, lines),
                        stops_away=away,
                        arrive_at=call.arrive_at,
                        diagnostics=EtaDiagnostics(
                            method=call.method, position_observed_at=v.position_observed_at
                        ),
                    )
                )
                break  # у кольцевых та же остановка может встретиться дважды: берём ближнюю
        found.sort(key=lambda a: a.arrive_at)
        per_line: dict[tuple[str, Direction], int] = {}
        arrivals: list[StopArrival] = []
        for item in found:
            key = (item.vehicle.line_id, item.vehicle.direction)
            if per_line.get(key, 0) < ARRIVALS_PER_LINE:
                per_line[key] = per_line.get(key, 0) + 1
                arrivals.append(item)
        return ArrivalsOutcome(stop, arrivals, snap)

    async def vehicle_details(self, vehicle_id: str) -> VehicleOutcome:
        """Машина и время её прихода на остановки впереди (для карточки машины).

        Машину открывают нажатием на карте, поэтому настройка «Низкопольный транспорт»
        здесь не фильтрует: правила «на линии» и «свежее положение» те же.
        """
        snap = await self.snapshot()
        network = await self.network()
        lines = await self.lines()
        ring_lines = frozenset(i for i, line in lines.items() if line.ring)
        now = self._clock()
        usable = self.visible_vehicles(snap, now, False)
        vehicle = next((v for v in usable if v.id == vehicle_id), None)
        if vehicle is None:
            return VehicleOutcome(None, None, [], snap)
        calls, _ = self.vehicle_calls(
            network, snap, now, False, ring_lines, now + self._s.horizon + RIDE_EXTRA
        ).get(vehicle_id, ([], None))
        next_stops = [
            NextStop(
                stop=call.stop,
                arrive_at=call.arrive_at,
                diagnostics=EtaDiagnostics(
                    method=call.method, position_observed_at=vehicle.position_observed_at
                ),
            )
            for call in calls[:VEHICLE_NEXT_STOPS]
        ]
        return VehicleOutcome(vehicle, network.toward(vehicle, lines), next_stops, snap)

    async def lines(self) -> dict[str, Line]:
        try:
            return {line.id: line for line in await self._live.lines()}
        except TransitFeedError as exc:
            raise TransitUnavailableError(str(exc)) from exc
