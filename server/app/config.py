"""Настройки сервера из переменных окружения (префикс GOPOINT_).

Пороги и скорости, влияющие на то, что видит пользователь, решает владелец.
Значения по умолчанию и источники записаны в docs/DECISIONS.md.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.models import Bounds, LatLon, TransportType

APP_NAME = "GoPoint"
APP_VERSION = "0.1.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GOPOINT_", extra="ignore")

    # Откуда сайту можно обращаться к API (CORS), через запятую.
    cors_origins: str = "http://localhost:5173,https://localhost"

    # Положение машины старше этого порога не используется и не показывается.
    stale_seconds: int = Field(default=300, ge=30)
    # Как часто сайт обновляет положения машин.
    refresh_interval_s: int = Field(default=30, ge=30)

    # Источник данных о транспорте: tsugaet (сайт ЦУГАЭТ) или fake (сохранённые образцы).
    transit_feed: Literal["tsugaet", "fake"] = "tsugaet"
    tsugaet_base_url: str = "https://map.nskgortrans.ru"
    # Пауза между запросами к ЦУГАЭТ и ожидание ответа.
    tsugaet_pause_s: float = Field(default=0.5, ge=0.5)
    tsugaet_timeout_s: float = Field(default=10.0, gt=0)
    # Папка с образцами для fake (относительно папки server/).
    fake_samples_dir: str = "../data/tsugaet/samples"
    # Опрос машин не чаще раза в poll_interval_s и только если к API обращались
    # за последние active_window_s. Частоту опроса ЦУГАЭТ меняет только владелец.
    poll_interval_s: int = Field(default=30, ge=30)
    active_window_s: int = Field(default=120, ge=30)
    # Список маршрутов и линии хранятся сутки.
    lines_ttl_s: int = Field(default=86_400, ge=3_600)
    # Какие виды транспорта берём, через запятую (маршрутки включены решением владельца 04.11.2026).
    transport_types: str = "bus,trolleybus,tram,minibus"

    # Границы Новосибирска (примерно, уточнить по границе из OpenStreetMap).
    city_south: float = 54.80
    city_west: float = 82.70
    city_north: float = 55.20
    city_east: float = 83.20

    @property
    def transport_type_set(self) -> frozenset[TransportType]:
        return frozenset(TransportType(t.strip()) for t in self.transport_types.split(",") if t)

    @property
    def user_agent(self) -> str:
        return f"{APP_NAME}/{APP_VERSION} (non-commercial accessible transit demo, Novosibirsk)"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def city_bounds(self) -> Bounds:
        return Bounds(
            south_west=LatLon(lat=self.city_south, lon=self.city_west),
            north_east=LatLon(lat=self.city_north, lon=self.city_east),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
