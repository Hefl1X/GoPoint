"""Ограничение частоты запросов к /api с одного адреса (CLAUDE.md, «Безопасность»).

Скользящее окно в 1 минуту, в памяти (базы в демо нет). Адрес берётся из соединения;
за Caddy это адрес из X-Forwarded-For (uvicorn --forwarded-allow-ips, сервер доступен
только из внутренней сети Docker). Адреса в журнал не пишутся.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta

from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.errors import api_error_response
from app.services.live_snapshot import Clock

WINDOW = timedelta(minutes=1)
# Сколько адресов помнить; при переполнении забываем самые старые записи.
MAX_KEYS = 10_000
MESSAGE = "Слишком много запросов. Подождите минуту."


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, *, per_minute: int, clock: Clock) -> None:
        self._app = app
        self._limit = per_minute
        self._clock = clock
        self._hits: dict[str, deque[datetime]] = {}

    def _allow(self, key: str) -> bool:
        now = self._clock()
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= MAX_KEYS:
                self._hits.pop(next(iter(self._hits)))
            hits = self._hits[key] = deque()
        while hits and now - hits[0] >= WINDOW:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith("/api/"):
            await self._app(scope, receive, send)
            return
        client = scope.get("client")
        key = client[0] if client else "unknown"
        if self._allow(key):
            await self._app(scope, receive, send)
            return
        response = api_error_response(429, "TOO_MANY_REQUESTS", MESSAGE)
        response.headers["Retry-After"] = str(int(WINDOW.total_seconds()))
        await response(scope, receive, send)
