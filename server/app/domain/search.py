"""Правила поиска адресов: чистые функции без сети.

Что считать одинаковым запросом, какие подсказки показывать и в каком порядке.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.domain.geo import distance_m
from app.domain.models import Bounds, LatLon, PlaceSuggestion

# Поиск начинается с трёх букв: короче подсказки бесполезны, а запросов много.
MIN_QUERY_LENGTH = 3
MAX_QUERY_LENGTH = 200
# Одно и то же место, записанное в OpenStreetMap несколько раз (здание и точка внутри).
DUPLICATE_RADIUS_M = 150

_SPACES = re.compile(r"\s+")


def normalize_query(query: str) -> str:
    """Запрос для поиска и ключ кэша: без лишних пробелов, «ё» как «е», строчные буквы."""
    text = _SPACES.sub(" ", query).strip().lower().replace("ё", "е")
    return text[:MAX_QUERY_LENGTH]


def is_searchable(query: str) -> bool:
    return len(normalize_query(query)) >= MIN_QUERY_LENGTH


def clean_suggestions(
    items: Iterable[PlaceSuggestion], bounds: Bounds, limit: int
) -> list[PlaceSuggestion]:
    """Только места в границах города, без повторов, не больше limit; порядок источника."""
    result: list[PlaceSuggestion] = []
    seen_ids: set[str] = set()
    for item in items:
        if not bounds.contains(item.point) or item.id in seen_ids:
            continue
        if any(_same_place(item, other) for other in result):
            continue
        seen_ids.add(item.id)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _same_place(a: PlaceSuggestion, b: PlaceSuggestion) -> bool:
    return (
        a.title.casefold() == b.title.casefold()
        and a.subtitle == b.subtitle
        and distance_m(a.point, b.point) <= DUPLICATE_RADIUS_M
    )


def cache_point(point: LatLon, digits: int = 4) -> tuple[float, float]:
    """Ключ кэша для точки: округление до ~10 м, чтобы соседние нажатия не ходили в сеть."""
    return (round(point.lat, digits), round(point.lon, digits))
