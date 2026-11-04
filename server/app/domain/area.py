"""Граница города: многоугольник (с дырами) и проверка «точка внутри». Чистые функции."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.models import Bounds, LatLon

Ring = Sequence[LatLon]


def _in_ring(point: LatLon, ring: Ring) -> bool:
    """Луч вправо от точки пересекает кольцо нечётное число раз (метод чётности)."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        a, b = ring[i], ring[j]
        if (a.lat > point.lat) != (b.lat > point.lat):
            cross = (b.lon - a.lon) * (point.lat - a.lat) / (b.lat - a.lat) + a.lon
            if point.lon < cross:
                inside = not inside
        j = i
    return inside


@dataclass(frozen=True)
class Polygon:
    outer: Ring
    holes: Sequence[Ring] = ()

    def contains(self, point: LatLon) -> bool:
        return _in_ring(point, self.outer) and not any(_in_ring(point, h) for h in self.holes)


@dataclass(frozen=True)
class CityArea:
    """Территория города. Без многоугольников используется прямоугольник bounds."""

    bounds: Bounds
    polygons: Sequence[Polygon] = ()

    def contains(self, point: LatLon) -> bool:
        if not self.bounds.contains(point):
            return False
        if not self.polygons:
            return True
        return any(p.contains(point) for p in self.polygons)
