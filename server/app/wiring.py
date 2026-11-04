"""Сборка приложения: какой адаптер за каким портом (выбирается настройкой).

Только этот модуль знает про конкретные адаптеры. Чтобы заменить источник,
достаточно новой папки в app/adapters/ и строчки здесь.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from app.adapters.fake.feed import FakeTransitFeed
from app.adapters.photon.geocoder import PhotonGeocoder
from app.adapters.tsugaet.feed import TsugaetFeed
from app.config import Settings
from app.ports import Geocoder, TransitFeed


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
