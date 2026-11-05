"""Ограничение частоты запросов к нашему API с одного адреса (CLAUDE.md, «Безопасность»)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters.fake.feed import FakeTransitFeed
from app.config import Settings
from app.main import create_app
from tests.conftest import SAMPLES, ManualClock
from tests.test_route_api import StraightWalker


def client(limit: int, clock: ManualClock) -> TestClient:
    app = create_app(
        Settings(transit_feed="fake", rate_limit_per_min=limit),
        feed=FakeTransitFeed(SAMPLES),
        walk_planner=StraightWalker(),
        clock=clock,
        start_poller=False,
    )
    return TestClient(app)


def test_too_many_requests_from_one_address_get_429_in_russian() -> None:
    clock = ManualClock()
    c = client(3, clock)
    for _ in range(3):
        assert c.get("/api/v1/meta").status_code == 200
    response = c.get("/api/v1/meta")
    assert response.status_code == 429
    assert response.json()["code"] == "TOO_MANY_REQUESTS"
    assert response.json()["message"] == "Слишком много запросов. Подождите минуту."
    assert response.headers["Retry-After"] == "60"


def test_limit_resets_after_a_minute() -> None:
    clock = ManualClock()
    c = client(2, clock)
    c.get("/api/v1/meta")
    c.get("/api/v1/meta")
    assert c.get("/api/v1/meta").status_code == 429
    clock.advance(61)
    assert c.get("/api/v1/meta").status_code == 200


def test_health_is_not_limited() -> None:
    clock = ManualClock()
    c = client(1, clock)
    for _ in range(5):
        assert c.get("/health").status_code == 200


def test_default_limit_is_generous_for_normal_use() -> None:
    # Обычный человек: обновление раз в 30 с (2–4 запроса в минуту), поиск и маршрут.
    assert Settings().rate_limit_per_min >= 120
