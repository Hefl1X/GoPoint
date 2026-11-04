"""Геометрия на линии маршрута. Чистые функции без сети.

Это простая версия для экрана «маршрут на линии»: ближайшая точка линии.
Точная проекция на отрезки и проверка по segment_order появятся в расчёте
прихода (запрос 6).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from app.domain.models import LatLon, LinePath

EARTH_RADIUS_M = 6_371_000


def distance_m(a: LatLon, b: LatLon) -> float:
    """Расстояние по формуле гаверсинусов, в метрах."""
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    dphi = phi2 - phi1
    dlmb = math.radians(b.lon - a.lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def nearest_point_index(points: Sequence[LatLon], point: LatLon) -> tuple[int, float]:
    """Номер ближайшей точки линии и расстояние до неё в метрах."""
    if not points:
        raise ValueError("пустая линия")
    best = min(range(len(points)), key=lambda i: distance_m(points[i], point))
    return best, distance_m(points[best], point)


def next_stop_order(path: LinePath, point: LatLon) -> int | None:
    """Порядковый номер следующей остановки впереди машины; None, если впереди их нет."""
    index, _ = nearest_point_index(path.points, point)
    for route_stop in path.stops:
        if route_stop.point_index > index:
            return route_stop.order
    return None
