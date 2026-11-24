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

from app.api import internal_rt, v1
from app.api.errors import install_error_handlers
from app.api.rate_limit import RateLimitMiddleware
from app.api.schemas import Health
from app.config import APP_NAME, APP_VERSION, Settings, get_settings
from app.domain.linear import EtaParams
from app.domain.low_floor import LowFloorSnapshot
from app.domain.schedule_snapshot import ScheduleSnapshot
from app.ports import Geocoder, TransitFeed, TransitPlanner, WalkPlanner
from app.services.geocoding import CachePolicy, GeocodingService
from app.services.journey_service import JourneyService, JourneySettings
from app.services.live_snapshot import Clock, LiveSnapshotService, utc_now
from app.services.live_transport import LiveTransportService, LiveTransportSettings
from app.services.realtime import RealtimeService
from app.services.walking import WalkingService
from app.wiring import (
    build_city_area,
    build_geocoder,
    build_local_places,
    build_realtime,
    build_transit_feed,
    build_transit_planner,
    build_walk_planner,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx пишет в журнал полный адрес каждого запроса, а в адресах к Photon есть координаты
# и текст поиска человека. Их в журнал не пишем (CLAUDE.md, «Безопасность»): только ошибки.
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


async def _start_realtime(
    app: FastAPI,
    settings: Settings,
    live: LiveSnapshotService,
    clock: Clock,
    schedule: ScheduleSnapshot | None,
) -> asyncio.Task[None] | None:
    try:
        realtime = await asyncio.to_thread(build_realtime, settings, live, clock, schedule)
    except (OSError, ValueError) as exc:
        logging.getLogger(__name__).warning("Комплект GTFS-Realtime недоступен: %s", exc)
        return None
    if realtime is None:
        return None
    await asyncio.to_thread(realtime.update)
    app.state.realtime = realtime
    return asyncio.create_task(realtime.run())


async def _stop_tasks(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


def _low_floor(app: FastAPI) -> LowFloorSnapshot | None:
    realtime: RealtimeService | None = app.state.realtime
    snapshot = realtime.current if realtime else None
    return snapshot.low_access if snapshot else None


def create_app(
    settings: Settings | None = None,
    *,
    feed: TransitFeed | None = None,
    geocoder: Geocoder | None = None,
    walk_planner: WalkPlanner | None = None,
    transit_planner: TransitPlanner | None = None,
    clock: Clock = utc_now,
    start_poller: bool = True,
    realtime_schedule: ScheduleSnapshot | None = None,
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
    close_transit: Callable[[], Awaitable[None]] | None = None
    if transit_planner is None:
        transit_planner, close_transit = build_transit_planner(settings)
    walking = WalkingService(walk_planner, cache_ttl_s=settings.walk_cache_ttl_s)
    live = LiveSnapshotService(
        feed,
        clock=clock,
        poll_interval_s=settings.poll_interval_s,
        active_window_s=settings.active_window_s,
        lines_ttl_s=settings.lines_ttl_s,
    )
    live_transport = LiveTransportService(
        live, clock=clock, settings=live_transport_settings(settings)
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        tasks: list[asyncio.Task[None]] = []
        try:
            task = await _start_realtime(_app, settings, live, clock, realtime_schedule)
            if task is not None:
                tasks.append(task)
            if start_poller:
                tasks.append(asyncio.create_task(live.run_poller()))
            yield
        finally:
            await _stop_tasks(tasks)
            _app.state.realtime = None
            for close in (close_transit, close_walk, close_geocoder, close_feed):
                if close:
                    await close()

    app = FastAPI(
        title=f"{APP_NAME} API",
        version=APP_VERSION,
        description="Маршруты по расписанию и транспорт Новосибирска на линии.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.realtime = None
    app.state.city = city
    app.state.live = live
    app.state.live_transport = live_transport
    geocoding.set_local(build_local_places(live.known_stops))
    app.state.geocoding = geocoding
    app.state.walking = walking
    app.state.journey_service = JourneyService(
        transit_planner,
        walking,
        clock=clock,
        low_floor=lambda: _low_floor(app),
        settings=JourneySettings(
            settings.walk_option_max_m, settings.board_margin_s, settings.transfer_margin_s
        ),
    )
    app.state.clock = clock
    _install_api(app, settings, clock)
    return app


def _install_api(app: FastAPI, settings: Settings, clock: Clock) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(RateLimitMiddleware, per_minute=settings.rate_limit_per_min, clock=clock)
    install_error_handlers(app)
    app.include_router(v1.router)
    app.include_router(internal_rt.router)

    @app.get("/health", include_in_schema=False)
    async def root_health() -> Health:
        return Health()


def live_transport_settings(settings: Settings) -> LiveTransportSettings:
    return LiveTransportSettings(
        eta=EtaParams(
            min_speed_mps=settings.vehicle_min_speed_kmh / 3.6,
            max_speed_mps=settings.vehicle_max_speed_kmh / 3.6,
            dwell_s=settings.dwell_s,
        ),
        stale_seconds=settings.stale_seconds,
        max_vehicle_offset_m=settings.max_vehicle_offset_m,
        horizon=timedelta(minutes=settings.horizon_min),
        snapshot_max_age=timedelta(seconds=settings.snapshot_max_age_s),
    )


app = create_app()
