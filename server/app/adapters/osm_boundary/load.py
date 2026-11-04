"""Граница города из GeoJSON (выгрузка OpenStreetMap). Порядок [lon, lat] известен только здесь.

Файл novosibirsk_city.geojson: «городской округ Новосибирск», relation 1751445,
выгрузка Geofabrik 02.11.2026, координаты округлены до 5 знаков (~1 м). Как обновить:
docs/ARCHITECTURE.md, раздел 12.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.domain.area import Polygon
from app.domain.models import LatLon

DEFAULT_FILE = Path(__file__).with_name("novosibirsk_city.geojson")


def _ring(raw: Any) -> list[LatLon]:
    return [LatLon(lat=float(lat), lon=float(lon)) for lon, lat in raw]


def parse_polygons(data: Any) -> list[Polygon]:
    polygons: list[Polygon] = []
    for feature in data.get("features", []):
        geometry = feature.get("geometry") or {}
        kind, coords = geometry.get("type"), geometry.get("coordinates") or []
        parts = coords if kind == "MultiPolygon" else [coords] if kind == "Polygon" else []
        for part in parts:
            if part:
                polygons.append(Polygon(outer=_ring(part[0]), holes=[_ring(r) for r in part[1:]]))
    if not polygons:
        raise ValueError("в файле границы нет многоугольников")
    return polygons


def load_polygons(path: Path = DEFAULT_FILE) -> list[Polygon]:
    return parse_polygons(json.loads(path.read_text(encoding="utf-8")))
