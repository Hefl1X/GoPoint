"""Остановки у точек А и Б и поездки, которые хуже пути пешком. Чистые функции без сети.

Остановки: раньше брались просто K ближайших. На узлах (вокзал, площадь Маркса) рядом
много остановок одного направления, и нужное направление в K не попадало (аудит 14.11).
Теперь: K ближайших вообще плюс для каждого маршрута и направления его ближайшая
остановка в радиусе; не больше max_total. Лимита расстояния по-прежнему нет: K ближайших
берутся, как бы далеко они ни были.

Поездки хуже пути пешком: если пешком от А до Б приезжаешь не позже или идёшь не больше,
чем в варианте с транспортом, такой вариант не нужен (иначе «4 км по кольцу на другую
сторону улицы»).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from app.domain.geo import distance_m
from app.domain.models import Journey, LatLon, LinePath, Stop, WalkLeg


def choose_access_stops(
    paths: Iterable[LinePath],
    point: LatLon,
    *,
    nearest: int,
    radius_m: float,
    max_total: int,
) -> list[Stop]:
    """Остановки для пешего участка у точки, ближайшие первыми."""
    stops: dict[str, tuple[float, Stop]] = {}
    per_pattern: dict[str, tuple[float, Stop]] = {}
    for p in paths:
        best: tuple[float, Stop] | None = None
        for rs in p.stops:
            d = distance_m(rs.stop.point, point)
            stops.setdefault(rs.stop.id, (d, rs.stop))
            if best is None or d < best[0]:
                best = (d, rs.stop)
        if best is not None and best[0] <= radius_m:
            per_pattern.setdefault(best[1].id, best)
    ordered = sorted(stops.values(), key=lambda x: x[0])
    chosen: dict[str, tuple[float, Stop]] = {s.id: (d, s) for d, s in ordered[:nearest]}
    for sid, item in sorted(per_pattern.items(), key=lambda x: x[1][0]):
        chosen.setdefault(sid, item)
    return [s for _, s in sorted(chosen.values(), key=lambda x: x[0])][:max_total]


def _walking_s(journey: Journey) -> int:
    return sum(leg.duration_s for leg in journey.legs if isinstance(leg, WalkLeg))


def drop_worse_than_walk(
    journeys: Sequence[Journey], walk: WalkLeg | None, now: datetime
) -> list[Journey]:
    """Оставить варианты на транспорте, которые быстрее пути пешком и с меньшей ходьбой."""
    if walk is None:
        return list(journeys)
    walk_arrive = now + timedelta(seconds=walk.duration_s)
    return [j for j in journeys if j.arrive_at < walk_arrive and _walking_s(j) < walk.duration_s]
