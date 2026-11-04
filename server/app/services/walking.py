"""Пешие участки: кэш ответов WalkPlanner (одни и те же пары точек считаются один раз).

Ключ кэша: точки, округлённые до ~10 м. Ошибки не кэшируются.
Координаты в журнал не пишутся.
"""

from __future__ import annotations

import time

from app.domain.models import Place, WalkLeg
from app.domain.search import cache_point
from app.ports import WalkPlanner
from app.services.cache import Monotonic, TtlCache


class WalkingService:
    def __init__(
        self,
        planner: WalkPlanner,
        *,
        cache_ttl_s: float = 86_400,
        cache_size: int = 5_000,
        now: Monotonic = time.monotonic,
    ) -> None:
        self._planner = planner
        self._cache: TtlCache[tuple[tuple[float, float], tuple[float, float]], WalkLeg] = TtlCache(
            ttl_s=cache_ttl_s, max_size=cache_size, now=now
        )
        self.requests_made = 0

    async def walk(self, origin: Place, destination: Place) -> WalkLeg:
        key = (cache_point(origin.point), cache_point(destination.point))
        hit, cached = self._cache.get(key)
        if hit and cached is not None:
            # Подписи точек у разных запросов могут отличаться: подставляем свои.
            return cached.model_copy(update={"origin": origin, "destination": destination})
        self.requests_made += 1
        leg = await self._planner.walk(origin, destination)
        self._cache.put(key, leg)
        return leg
