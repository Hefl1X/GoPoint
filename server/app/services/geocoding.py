"""Поиск адресов: кэш и бережная нагрузка на сервис поиска.

Публичный Photon рассчитан на небольшую нагрузку, поэтому:
- одинаковые запросы берутся из кэша в памяти (по умолчанию сутки);
- в сервис уходит не больше одного запроса за min_interval_s, остальные ждут очереди;
- в журнал не пишутся ни тексты запросов, ни координаты.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.domain.area import CityArea
from app.domain.models import LatLon, PlaceSuggestion
from app.domain.search import cache_point, clean_suggestions, is_searchable, normalize_query
from app.ports import Geocoder
from app.services.cache import Monotonic, TtlCache


@dataclass(frozen=True)
class CachePolicy:
    ttl_s: float = 86_400
    max_size: int = 2_000


class GeocodingService:
    def __init__(
        self,
        geocoder: Geocoder,
        *,
        area: CityArea,
        near: LatLon,
        limit: int = 6,
        cache: CachePolicy = CachePolicy(),  # noqa: B008  неизменяемый объект
        min_interval_s: float = 0.2,
        now: Monotonic = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._geocoder = geocoder
        self._bounds = area.bounds
        self._area = area
        self._near = near
        self._limit = limit
        self._min_interval_s = min_interval_s
        self._now = now
        self._sleep = sleep
        self._search_cache: TtlCache[str, list[PlaceSuggestion]] = TtlCache(
            ttl_s=cache.ttl_s, max_size=cache.max_size, now=now
        )
        self._reverse_cache: TtlCache[tuple[float, float], PlaceSuggestion | None] = TtlCache(
            ttl_s=cache.ttl_s, max_size=cache.max_size, now=now
        )
        self._lock = asyncio.Lock()
        self._last_request = -1e9
        self.requests_made = 0  # для проверки нагрузки на сервис поиска

    @property
    def area(self) -> CityArea:
        return self._area

    async def _throttled[T](self, call: Callable[[], Awaitable[T]]) -> T:
        # Один запрос за раз и пауза между ними, сколько бы людей ни искало.
        async with self._lock:
            wait = self._last_request + self._min_interval_s - self._now()
            if wait > 0:
                await self._sleep(wait)
            try:
                self.requests_made += 1
                return await call()
            finally:
                self._last_request = self._now()

    async def search(self, query: str) -> list[PlaceSuggestion]:
        """Подсказки в границах города. Короткий запрос (меньше 3 букв) даёт пустой список."""
        if not is_searchable(query):
            return []
        key = normalize_query(query)
        hit, cached = self._search_cache.get(key)
        if hit and cached is not None:
            return cached
        raw = await self._throttled(
            lambda: self._geocoder.search(
                key, limit=self._limit, bounds=self._bounds, near=self._near
            )
        )
        inside = [item for item in raw if self._area.contains(item.point)]
        result = clean_suggestions(inside, self._bounds, self._limit)
        self._search_cache.put(key, result)
        return result

    async def reverse(self, point: LatLon) -> PlaceSuggestion | None:
        """Адрес у точки на карте; None, если рядом ничего нет или нашлось за границей города."""
        key = cache_point(point)
        hit, cached = self._reverse_cache.get(key)
        if hit:
            return cached
        found = await self._throttled(lambda: self._geocoder.reverse(point))
        result = found if found is not None and self._area.contains(found.point) else None
        self._reverse_cache.put(key, result)
        return result
