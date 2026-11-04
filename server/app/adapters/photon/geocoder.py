"""Geocoder на Photon (поиск по данным OpenStreetMap).

Для демо используется публичный сервер photon.komoot.io: он разрешает
«разумное» число запросов, при большой нагрузке ограничивает или блокирует
(https://photon.komoot.io, проверено 2026-11-04). Поэтому наш сервер кэширует
ответы и выдерживает паузу между запросами (app/services/geocoding.py).
Адрес сервера в настройке GOPOINT_PHOTON_URL: свой экземпляр подключается без кода.
Координаты пользователей в Photon не уходят: смещение поиска к центру города.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.adapters.photon.parse import PhotonFormatError, parse_features
from app.domain.models import Bounds, LatLon, PlaceSuggestion
from app.ports import GeocoderError

DEFAULT_BASE_URL = "https://photon.komoot.io"
# Без перевода: названия как в OpenStreetMap (в Новосибирске по-русски).
# Публичный сервер знает только default, de, en, fr (ответ на lang=ru, 2026-11-04).
LANGUAGE = "default"
# Насколько далеко от точки ищет обратный поиск, км.
REVERSE_RADIUS_KM = 0.3


class PhotonGeocoder:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str,
        timeout_s: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            transport=transport,
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, str]) -> list[PlaceSuggestion]:
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise GeocoderError(f"Photon {path}: нет ответа ({type(exc).__name__})") from exc
        if response.status_code != httpx.codes.OK:
            raise GeocoderError(f"Photon {path}: код {response.status_code}")
        try:
            body: Any = response.json()
            return parse_features(body)
        except (ValueError, PhotonFormatError) as exc:
            raise GeocoderError(f"Photon {path}: непонятный ответ") from exc

    async def search(
        self, query: str, *, limit: int, bounds: Bounds, near: LatLon
    ) -> list[PlaceSuggestion]:
        sw, ne = bounds.south_west, bounds.north_east
        params = {
            "q": query,
            # Запас на повторы и места за границей: лишнее отсекает сервис.
            "limit": str(limit + 4),
            "lang": LANGUAGE,
            # Порядок по документации: minLon,minLat,maxLon,maxLat.
            "bbox": f"{sw.lon},{sw.lat},{ne.lon},{ne.lat}",
            "lat": str(near.lat),
            "lon": str(near.lon),
        }
        return await self._get("/api/", params)

    async def reverse(self, point: LatLon) -> PlaceSuggestion | None:
        params = {
            "lat": str(point.lat),
            "lon": str(point.lon),
            "limit": "1",
            "lang": LANGUAGE,
            "radius": str(REVERSE_RADIUS_KM),
        }
        items = await self._get("/reverse", params)
        return items[0] if items else None
