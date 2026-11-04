"""Вырезать из выгрузки Photon (JSON dump 0.1.0) только места в прямоугольнике города.

Читает строки JSON со стандартного ввода, пишет подходящие на стандартный вывод.
Формат: https://github.com/komoot/photon/blob/master/docs/json-dump-format-0.1.0.md

Оставляем:
- служебные строки (заголовок NominatimDumpFile, CountryInfo);
- места, центр которых внутри прямоугольника;
- только если в заголовке has_addresslines = true: ещё и области (область, район, город,
  микрорайон), чей прямоугольник пересекает наш, потому что адреса домов ссылаются на них.
  В выгрузке GraphHopper от 31.10.2026 has_addresslines = false: адрес записан в каждом месте.
Порядок строк сохраняется: по формату область должна стоять раньше ссылок на неё.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Iterator
from typing import Any

Box = tuple[float, float, float, float]  # юг, запад, север, восток

AREA_TYPES = {"country", "state", "county", "city", "district", "locality"}
# Ранги Nominatim для тех же уровней (если вместо address_type дан rank_address).
MAX_AREA_RANK = 24


def parse_box(text: str) -> Box:
    south, west, north, east = (float(x) for x in text.split(","))
    if south >= north or west >= east:
        raise ValueError("ожидается юг,запад,север,восток")
    return south, west, north, east


def point_inside(lon: float, lat: float, box: Box) -> bool:
    south, west, north, east = box
    return south <= lat <= north and west <= lon <= east


def is_area(item: dict[str, Any]) -> bool:
    if item.get("address_type") in AREA_TYPES:
        return True
    rank = item.get("rank_address")
    return isinstance(rank, int) and 0 < rank <= MAX_AREA_RANK and "housenumber" not in item


def bbox_intersects(bbox: Any, box: Box) -> bool:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return False
    x1, y1, x2, y2 = (float(v) for v in bbox)
    south, west, north, east = box
    return (
        min(x1, x2) <= east
        and max(x1, x2) >= west
        and min(y1, y2) <= north
        and max(y1, y2) >= south
    )


def keep_item(item: dict[str, Any], box: Box, keep_areas: bool) -> bool:
    centroid = item.get("centroid")
    if (
        isinstance(centroid, list)
        and len(centroid) == 2
        and point_inside(float(centroid[0]), float(centroid[1]), box)
    ):
        return True
    return keep_areas and is_area(item) and bbox_intersects(item.get("bbox"), box)


def extract(lines: Iterable[str], box: Box) -> Iterator[str]:
    """Строки выгрузки, которые нужно оставить (с переводом строки в конце)."""
    keep_areas = True  # без заголовка считаем, что ссылки есть: лишнее безопаснее потерянного
    for line in lines:
        if not line.strip():
            continue
        record = json.loads(line)
        kind = record.get("type")
        content = record.get("content")
        if kind == "NominatimDumpFile" and isinstance(content, dict):
            features = content.get("features") or {}
            keep_areas = bool(features.get("has_addresslines", True))
        if kind == "Place":
            items = content if isinstance(content, list) else [content]
            if not any(isinstance(i, dict) and keep_item(i, box, keep_areas) for i in items):
                continue
        yield line if line.endswith("\n") else line + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", required=True, help="юг,запад,север,восток")
    args = parser.parse_args()
    kept = 0
    for line in extract(sys.stdin, parse_box(args.bbox)):
        kept += 1
        sys.stdout.write(line)
    print(f"Оставлено строк: {kept}", file=sys.stderr)


if __name__ == "__main__":
    main()
