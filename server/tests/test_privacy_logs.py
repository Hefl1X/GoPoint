"""Координаты и текст поиска человека не попадают в журнал сервера (CLAUDE.md, «Безопасность»).

Баг 05.11: журнал доступа был выключен, но библиотека httpx писала в журнал (INFO) полный
адрес каждого запроса к Photon: /reverse?lat=…&lon=… и /api/?q=…&lat=…&lon=…
"""

from __future__ import annotations

import logging

import httpx
import pytest

import app.main  # noqa: F401  (настройка журнала при запуске сервера)
from app.adapters.photon.geocoder import PhotonGeocoder
from app.domain.models import Bounds, LatLon

POINT = LatLon(lat=55.012345, lon=82.954321)
BOUNDS = Bounds(south_west=LatLon(lat=54.8, lon=82.7), north_east=LatLon(lat=55.2, lon=83.2))


async def test_photon_requests_do_not_log_coordinates_or_query(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    g = PhotonGeocoder(
        base_url="https://photon.test",
        user_agent="GoPoint/test",
        transport=httpx.MockTransport(handle),
    )
    # Как на работающем сервере: общий уровень журнала INFO (app.main).
    caplog.set_level(logging.INFO)
    await g.reverse(POINT)
    await g.search("улица тестовая", limit=6, bounds=BOUNDS, near=POINT)
    await g.aclose()

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "55.012345" not in text
    assert "82.954321" not in text
    assert "%D1%83%D0%BB" not in text and "тестовая" not in text
