"""Точка входа сервера GoPoint."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import v1
from app.api.errors import install_error_handlers
from app.api.rate_limit import RateLimitMiddleware
from app.api.schemas import Health
from app.config import APP_NAME, APP_VERSION, Settings, get_settings
from app.domain.journey_search import SearchParams
from app.domain.linear import EtaParams
from app.ports import Geocoder, TransitFeed, WalkPlanner
from app.services.geocoding import CachePolicy, GeocodingService
from app.services.journey_planner import JourneyPlanner, PlannerSettings
from app.services.live_snapshot import Clock, LiveSnapshotService, utc_now
from app.services.walking import WalkingService
from app.wiring import (
    build_city_area,
    build_geocoder,
    build_transit_feed,
    build_walk_planner,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx пишет в журнал полный адрес каждого запроса, а в адресах к Photon есть координаты
# и текст поиска человека. Их в журнал не пишем (CLAUDE.md, «Безопасность»): только ошибки.
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def create_app(
    settings: Settings | None = None,
    *,
    feed: TransitFeed | None = None,
    geocoder: Geocoder | None = None,
    walk_planner: WalkPlanner | None = None,
    clock: Clock = utc_now,
    start_poller: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    close_feed: Callable[[], Awaitable[None]] | None = None
    if feed is None:
        feed, close_feed = build_transit_feed(settings)
    city = build_city_area(settings)
    close_geocoder: Callable[[], Awaitable[None]] | None = None
    if geocoder is None:
        geocoder, close_geocoder = build_geocoder(settings)
    geocoding = GeocodingService(
        geocoder,
        area=city,
        near=settings.city_center,
        limit=settings.search_limit,
        cache=CachePolicy(ttl_s=settings.search_cache_ttl_s, max_size=settings.search_cache_size),
        min_interval_s=settings.photon_min_interval_s,
    )
    close_walk: Callable[[], Awaitable[None]] | None = None
    if walk_planner is None:
        walk_planner, close_walk = build_walk_planner(settings)
    walking = WalkingService(walk_planner, cache_ttl_s=settings.walk_cache_ttl_s)
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
            if close_geocoder:
                await close_geocoder()
            if close_walk:
                await close_walk()

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
    app.state.city = city
    app.state.live = live
    app.state.geocoding = geocoding
    app.state.walking = walking
    app.state.planner = JourneyPlanner(
        live,
        walking,
        clock=clock,
        settings=planner_settings(settings),
    )
    app.state.clock = clock
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(RateLimitMiddleware, per_minute=settings.rate_limit_per_min, clock=clock)
    install_error_handlers(app)
    app.include_router(v1.router)

    @app.get("/health", include_in_schema=False)
    async def root_health() -> Health:
        return Health()

    return app


def planner_settings(settings: Settings) -> PlannerSettings:
    return PlannerSettings(
        eta=EtaParams(
            min_speed_mps=settings.vehicle_min_speed_kmh / 3.6,
            max_speed_mps=settings.vehicle_max_speed_kmh / 3.6,
            dwell_s=settings.dwell_s,
        ),
        search=SearchParams(
            board_margin_s=settings.board_margin_s,
            transfer_margin_s=settings.transfer_margin_s,
            board_within_s=settings.horizon_min * 60,
        ),
        stale_seconds=settings.stale_seconds,
        max_vehicle_offset_m=settings.max_vehicle_offset_m,
        transfer_radius_m=settings.transfer_radius_m,
        access_stops=settings.access_stops,
        horizon=timedelta(minutes=settings.horizon_min),
        walk_speed_mps=settings.walk_speed_mps,
        snapshot_max_age=timedelta(seconds=settings.snapshot_max_age_s),
        walk_option_max_m=settings.walk_option_max_m,
        access_radius_m=settings.access_radius_m,
        access_stops_max=settings.access_stops_max,
    )


app = create_app()
