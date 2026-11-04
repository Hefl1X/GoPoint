"""Настоящий сайт ЦУГАЭТ. Запуск только вручную: uv run pytest -m network

Делает 4 запроса: список маршрутов, машины одного маршрута, линия, всё с паузой.
"""

import pytest

from app.adapters.tsugaet.feed import TsugaetFeed
from app.config import get_settings
from app.domain.models import Direction, TransportType

pytestmark = pytest.mark.network


async def test_live_site_format_unchanged() -> None:
    feed = TsugaetFeed(user_agent=get_settings().user_agent, pause_s=1.0)
    try:
        lines = await feed.lines()
        assert len(lines) > 50
        bus = next(line for line in lines if line.type is TransportType.BUS)
        vehicles = await feed.vehicles([bus.id])
        assert all(v.vehicle.line_id == bus.id for v in vehicles)
        path = await feed.line_path(bus.id, Direction.A)
        assert path.stops
    finally:
        await feed.aclose()
