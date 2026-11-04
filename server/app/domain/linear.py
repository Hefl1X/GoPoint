"""Положение машины на линии маршрута и время прихода на остановки впереди.

Чистые функции без сети. Раздел 8 docs/ARCHITECTURE.md, пункты 1–2.

1. Точка положения проецируется на отрезки линии своего направления. Если линия
   проходит рядом с точкой несколько раз (петля), берётся вариант, согласный с
   segment_order (±1); segment_order = 0 значит «неизвестно» (docs/DATA_QUALITY.md).
   Машина дальше max_offset_m от линии в расчёт не берётся.
2. Время прихода на остановку впереди: по плану машины (rasp), если остановка в нём
   есть, время ещё не прошло и оно не дальше plan_tolerance_s от расчёта по расстоянию
   (в плане бывают времена следующего круга той же машины); иначе расстояние вдоль
   линии / скорость (не ниже MIN_SPEED и не выше MAX_SPEED) плюс DWELL на каждой
   промежуточной остановке.
   Способ записывается в служебное поле, интерфейс его не называет.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.geo import EARTH_RADIUS_M
from app.domain.models import EtaMethod, LatLon, LinePath, LiveVehicle, PlannedStop, Stop

# Остановка «впереди», если она дальше текущего положения больше чем на это.
_AHEAD_EPS_M = 1.0


@dataclass(frozen=True)
class LineGeometry:
    path: LinePath
    cumulative_m: list[float]  # расстояние от начала линии до каждой точки
    stop_along_m: list[float]  # расстояние до каждой остановки (по порядку path.stops)

    @property
    def length_m(self) -> float:
        return self.cumulative_m[-1]


def _xy(origin: LatLon, p: LatLon) -> tuple[float, float]:
    """Плоские координаты точки в метрах около origin (для коротких отрезков точно)."""
    k = math.cos(math.radians(origin.lat))
    return (
        math.radians(p.lon - origin.lon) * k * EARTH_RADIUS_M,
        math.radians(p.lat - origin.lat) * EARTH_RADIUS_M,
    )


def build_geometry(path: LinePath) -> LineGeometry:
    cumulative = [0.0]
    for a, b in zip(path.points, path.points[1:], strict=False):
        x, y = _xy(a, b)
        cumulative.append(cumulative[-1] + math.hypot(x, y))
    stops = [cumulative[s.point_index] for s in path.stops]
    return LineGeometry(path=path, cumulative_m=cumulative, stop_along_m=stops)


@dataclass(frozen=True)
class Projection:
    along_m: float  # расстояние вдоль линии от её начала
    offset_m: float  # насколько точка в стороне от линии


def _segment_projections(geom: LineGeometry, point: LatLon) -> list[Projection]:
    result: list[Projection] = []
    pts = geom.path.points
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        bx, by = _xy(a, b)
        px, py = _xy(a, point)
        seg2 = bx * bx + by * by
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, (px * bx + py * by) / seg2))
        dx, dy = px - t * bx, py - t * by
        result.append(
            Projection(
                along_m=geom.cumulative_m[i] + t * math.sqrt(seg2), offset_m=math.hypot(dx, dy)
            )
        )
    return result


def stops_passed(geom: LineGeometry, along_m: float) -> int:
    """Сколько остановок направления уже позади (стоящая на остановке машина её «проехала»)."""
    return sum(1 for d in geom.stop_along_m if d <= along_m + _AHEAD_EPS_M)


def locate(
    geom: LineGeometry, point: LatLon, *, max_offset_m: float, segment_order: int | None
) -> Projection | None:
    """Положение машины на линии или None, если она далеко от линии."""
    near = [p for p in _segment_projections(geom, point) if p.offset_m <= max_offset_m]
    if not near:
        return None
    # Подряд идущие близкие отрезки — один проход мимо точки; из каждого берём лучший.
    candidates: list[Projection] = []
    for p in sorted(near, key=lambda p: p.along_m):
        if candidates and p.along_m - candidates[-1].along_m <= max_offset_m * 2:
            if p.offset_m < candidates[-1].offset_m:
                candidates[-1] = p
        else:
            candidates.append(p)
    if segment_order:
        agreeing = [
            c for c in candidates if abs(stops_passed(geom, c.along_m) - segment_order) <= 1
        ]
        if agreeing:
            return min(agreeing, key=lambda c: c.offset_m)
    return min(candidates, key=lambda c: c.offset_m)


@dataclass(frozen=True)
class EtaParams:
    min_speed_mps: float
    max_speed_mps: float
    dwell_s: float
    plan_tolerance_s: float = 600


@dataclass(frozen=True)
class StopCall:
    """Машина придёт на остановку в это время (UTC)."""

    stop: Stop
    order: int  # номер остановки в направлении
    arrive_at: datetime
    method: EtaMethod


_NAME_JUNK = re.compile(r"[\"«»'“”„().,\-]")


def normalize_stop_name(name: str) -> str:
    """Название остановки для сравнения плана (rasp) и линии (trasses)."""
    text = _NAME_JUNK.sub(" ", name.lower().replace("ё", "е"))
    return " ".join(text.split())


def _planned_time(
    plan: list[PlannedStop], stop: Stop, now: datetime, estimate: datetime, tolerance: timedelta
) -> datetime | None:
    key = normalize_stop_name(stop.name)
    for item in plan:
        if (
            item.at > now
            and abs(item.at - estimate) <= tolerance
            and normalize_stop_name(item.stop_name) == key
        ):
            return item.at
    return None


def stop_calls(
    geom: LineGeometry,
    projection: Projection,
    live: LiveVehicle,
    *,
    now: datetime,
    horizon: datetime,
    params: EtaParams,
    ring: bool = False,
) -> list[StopCall]:
    """Остановки впереди машины с временем прихода, по порядку движения.

    Остановки, время прихода на которые уже прошло (положение отстаёт на 30–60 с),
    считаются проеханными и не попадают в список. У кольцевого маршрута после
    последней остановки список продолжается с начала линии.
    """
    vehicle = live.vehicle
    speed_kmh = vehicle.speed_kmh if vehicle.speed_kmh is not None else 0.0
    speed = min(max(speed_kmh / 3.6, params.min_speed_mps), params.max_speed_mps)
    stops = geom.path.stops
    ahead: list[tuple[float, int]] = [
        (d - projection.along_m, i)
        for i, d in enumerate(geom.stop_along_m)
        if d > projection.along_m + _AHEAD_EPS_M
    ]
    if ring and stops:
        rest = geom.length_m - projection.along_m
        first_id = stops[0].stop.id
        last_id = stops[-1].stop.id
        for i, d in enumerate(geom.stop_along_m):
            if d > projection.along_m + _AHEAD_EPS_M:
                break
            if i == 0 and first_id == last_id:
                continue  # та же остановка, что последняя: уже в списке
            ahead.append((rest + d, i))

    calls: list[StopCall] = []
    for between, (distance, i) in enumerate(ahead):
        stop = stops[i].stop
        estimate = vehicle.position_observed_at + timedelta(
            seconds=distance / speed + params.dwell_s * between
        )
        planned = _planned_time(
            live.plan, stop, now, estimate, timedelta(seconds=params.plan_tolerance_s)
        )
        if planned is not None:
            arrive, method = planned, EtaMethod.PLANNED
        else:
            arrive, method = estimate, EtaMethod.DISTANCE
        # Время по остановкам не идёт назад, даже если план и расчёт расходятся.
        if calls and arrive < calls[-1].arrive_at:
            arrive = calls[-1].arrive_at
        if arrive > horizon:
            break
        if arrive < now:
            continue
        calls.append(StopCall(stop=stop, order=stops[i].order, arrive_at=arrive, method=method))
    return calls
