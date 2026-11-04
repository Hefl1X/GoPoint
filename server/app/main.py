"""Точка входа сервера GoPoint."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import v1
from app.api.errors import install_error_handlers
from app.api.schemas import Health
from app.config import APP_NAME, APP_VERSION, Settings, get_settings
from app.ports import TransitFeed
from app.services.live_snapshot import Clock, LiveSnapshotService, utc_now
from app.wiring import build_transit_feed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(
    settings: Settings | None = None,
    *,
    feed: TransitFeed | None = None,
    clock: Clock = utc_now,
    start_poller: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    close_feed: Callable[[], Awaitable[None]] | None = None
    if feed is None:
        feed, close_feed = build_transit_feed(settings)
    live = LiveSnapshotService(
        feed,
        clock=clock,
        poll_interval_s=settings.poll_interval_s,
        active_window_s=settings.active_window_s,
        lines_ttl_s=settings.lines_ttl_s,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        poller = asyncio.create_task(live.run_poller()) if start_poller else None
        try:
            yield
        finally:
            if poller:
                poller.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await poller
            if close_feed:
                await close_feed()

    app = FastAPI(
        title=f"{APP_NAME} API",
        version=APP_VERSION,
        description="Транспорт Новосибирска на линии сейчас и маршруты по низкопольным машинам.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.live = live
    app.state.clock = clock
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    install_error_handlers(app)
    app.include_router(v1.router)

    @app.get("/health", include_in_schema=False)
    async def root_health() -> Health:
        return Health()

    return app


app = create_app()
