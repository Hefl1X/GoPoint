"""Небольшой кэш в памяти со сроком годности (базы данных в демо нет)."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable

Monotonic = Callable[[], float]


class TtlCache[K, V]:
    """Небольшой кэш: старые записи вытесняются, у каждой срок годности."""

    def __init__(self, *, ttl_s: float, max_size: int, now: Monotonic) -> None:
        self._ttl_s = ttl_s
        self._max_size = max_size
        self._now = now
        self._items: OrderedDict[K, tuple[float, V]] = OrderedDict()

    def get(self, key: K) -> tuple[bool, V | None]:
        entry = self._items.get(key)
        if entry is None:
            return False, None
        stored_at, value = entry
        if self._now() - stored_at > self._ttl_s:
            del self._items[key]
            return False, None
        self._items.move_to_end(key)
        return True, value

    def put(self, key: K, value: V) -> None:
        self._items[key] = (self._now(), value)
        self._items.move_to_end(key)
        while len(self._items) > self._max_size:
            self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)
