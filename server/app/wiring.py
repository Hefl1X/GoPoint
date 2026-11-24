"""Сборка приложения: какой адаптер за каким портом (выбирается настройкой).

Только этот модуль знает про конкретные адаптеры. Чтобы заменить источник,
достаточно новой папки в app/adapters/ и строчки здесь.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path

from app.adapters.fake.feed import FakeTransitFeed
from app.adapters.gtfs_rt import GtfsRealtimeEncoder
from app.adapters.local_places import LocalPlacesProvider
from app.adapters.osm_boundary.load import DEFAULT_FILE, load_polygons
from app.adapters.otp.schedule import load_release_schedule
from app.adapters.otp.walk import OtpWalkPlanner
from app.adapters.photon.geocoder import PhotonGeocoder
from app.adapters.tsugaet.feed import TsugaetFeed
from app.config import Settings
from app.domain.area import CityArea
from app.domain.models import Stop
from app.domain.schedule_snapshot import ScheduleSnapshot
from app.domain.trip_match import DEFAULT_MATCH_SETTINGS
from app.ports import Geocoder, TransitFeed, WalkPlanner
from app.services.live_snapshot import Clock, LiveSnapshotService
from app.services.realtime import RealtimeService


async def _noop() -> None:
    return None


def build_transit_feed(settings: Settings) -> tuple[TransitFeed, Callable[[], Awaitable[None]]]:
    """Адаптер TransitFeed и функция его закрытия."""
    if settings.transit_feed == "fake":
        samples = Path(settings.fake_samples_dir)
        if not samples.is_absolute():
            samples = Path(__file__).resolve().parents[1] / samples
        return FakeTransitFeed(samples), _noop

    feed = TsugaetFeed(
        base_url=settings.tsugaet_base_url,
        user_agent=settings.user_agent,
        timeout_s=settings.tsugaet_timeout_s,
        pause_s=settings.tsugaet_pause_s,
        types=settings.transport_type_set,
    )
    return feed, feed.aclose


def build_geocoder(settings: Settings) -> tuple[Geocoder, Callable[[], Awaitable[None]]]:
    """Адаптер Geocoder и функция его закрытия."""
    geocoder = PhotonGeocoder(
        base_url=settings.photon_url,
        user_agent=settings.user_agent,
        timeout_s=settings.photon_timeout_s,
    )
    return geocoder, geocoder.aclose


def build_local_places(known_stops: Callable[[], list[Stop]]) -> LocalPlacesProvider:
    """Свои подсказки поиска: синонимы из файла и остановки ЦУГАЭТ."""
    return LocalPlacesProvider(known_stops)


def build_walk_planner(settings: Settings) -> tuple[WalkPlanner, Callable[[], Awaitable[None]]]:
    """Адаптер WalkPlanner и функция его закрытия."""
    planner = OtpWalkPlanner(
        base_url=settings.otp_url,
        speed_mps=settings.walk_speed_mps,
        timeout_s=settings.otp_timeout_s,
    )
    return planner, planner.aclose


def build_realtime(
    settings: Settings, live: LiveSnapshotService, clock: Clock, schedule: ScheduleSnapshot | None
) -> RealtimeService | None:
    if schedule is None and settings.realtime_release is not None:
        schedule = load_release_schedule(settings.realtime_release)
    if schedule is None:
        return None
    return RealtimeService(
        live,
        schedule,
        GtfsRealtimeEncoder(),
        clock=clock,
        settings=replace(
            DEFAULT_MATCH_SETTINGS,
            stale_s=settings.stale_seconds,
            max_offset_m=settings.max_vehicle_offset_m,
        ),
    )


def build_city_area(settings: Settings) -> CityArea:
    """Территория города: прямоугольник из настроек и граница из OpenStreetMap."""
    path = Path(settings.city_boundary_file) if settings.city_boundary_file else DEFAULT_FILE
    return CityArea(bounds=settings.city_bounds, polygons=load_polygons(path))
