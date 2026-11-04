"""Поиск адресов: правила, кэш, нагрузка на Photon и адреса API (без сети)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.models import Bounds, LatLon, PlaceKind, PlaceSuggestion
from app.domain.search import clean_suggestions, is_searchable, normalize_query
from app.main import create_app
from app.ports import GeocoderError
from app.services.geocoding import CachePolicy, GeocodingService
from tests.conftest import ManualClock

BOUNDS = Bounds(south_west=LatLon(lat=54.8, lon=82.7), north_east=LatLon(lat=55.2, lon=83.2))
CENTER = LatLon(lat=55.03, lon=82.92)


def place(
    pid: str, title: str, lat: float = 55.03, lon: float = 82.92, **kw: Any
) -> PlaceSuggestion:
    return PlaceSuggestion(
        id=pid,
        title=title,
        kind=kw.pop("kind", PlaceKind.PLACE),
        point=LatLon(lat=lat, lon=lon),
        **kw,
    )


class StubGeocoder:
    def __init__(self, items: list[PlaceSuggestion] | None = None) -> None:
        self.items = items or []
        self.reverse_result: PlaceSuggestion | None = None
        self.fail = False
        self.queries: list[str] = []
        self.reverse_calls = 0

    async def search(
        self, query: str, *, limit: int, bounds: Bounds, near: LatLon
    ) -> list[PlaceSuggestion]:
        self.queries.append(query)
        if self.fail:
            raise GeocoderError("нет ответа")
        return self.items

    async def reverse(self, point: LatLon) -> PlaceSuggestion | None:
        self.reverse_calls += 1
        if self.fail:
            raise GeocoderError("нет ответа")
        return self.reverse_result


class FakeTime:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


def service(geo: StubGeocoder, time: FakeTime | None = None) -> GeocodingService:
    t = time or FakeTime()
    return GeocodingService(
        geo, bounds=BOUNDS, near=CENTER, limit=3, cache=CachePolicy(ttl_s=60), now=t, sleep=t.sleep
    )


# --- правила ---


def test_normalize_query() -> None:
    assert normalize_query("  Красный   Проспект 25 ") == "красный проспект 25"
    assert normalize_query("Пётр") == "петр"
    assert len(normalize_query("а" * 500)) == 200


def test_is_searchable_needs_three_letters() -> None:
    assert not is_searchable("  ле  ")
    assert is_searchable("лен")


def test_clean_drops_outside_city_duplicates_and_extra() -> None:
    items = [
        place("1", "Аура"),
        place("2", "Толмачёво", lat=55.01, lon=82.65),  # аэропорт за границей города
        place("3", "аура", lat=55.0301),  # тот же ТЦ второй записью рядом
        place("1", "Аура"),
        place("4", "Аура", lat=55.1),  # однофамилец далеко: оставляем
        place("5", "Мега"),
        place("6", "Галерея"),
    ]
    assert [i.id for i in clean_suggestions(items, BOUNDS, 3)] == ["1", "4", "5"]


# --- сервис ---


async def test_short_query_does_not_call_photon() -> None:
    geo = StubGeocoder()
    assert await service(geo).search("ле ") == []
    assert geo.queries == []


async def test_same_query_is_cached() -> None:
    geo = StubGeocoder([place("1", "Аура")])
    s = service(geo)
    assert [i.title for i in await s.search("Аура")] == ["Аура"]
    assert [i.title for i in await s.search("  аура ")] == ["Аура"]
    assert geo.queries == ["аура"]


async def test_cache_expires() -> None:
    geo = StubGeocoder([place("1", "Аура")])
    t = FakeTime()
    s = service(geo, t)
    await s.search("аура")
    t.t += 61
    await s.search("аура")
    assert len(geo.queries) == 2


async def test_requests_to_photon_are_spaced() -> None:
    geo = StubGeocoder([place("1", "Аура")])
    t = FakeTime()
    s = service(geo, t)
    await s.search("аура")
    await s.search("мега")
    assert t.slept == [pytest.approx(0.2)]
    assert s.requests_made == 2


async def test_failure_is_not_cached() -> None:
    geo = StubGeocoder([place("1", "Аура")])
    geo.fail = True
    s = service(geo)
    with pytest.raises(GeocoderError):
        await s.search("аура")
    geo.fail = False
    assert len(await s.search("аура")) == 1


async def test_reverse_cached_by_nearby_point_and_outside_city_is_none() -> None:
    geo = StubGeocoder()
    geo.reverse_result = place("9", "Где-то", lat=56.0)  # нашлось за границей города
    s = service(geo)
    assert await s.reverse(LatLon(lat=55.03001, lon=82.92001)) is None
    assert await s.reverse(LatLon(lat=55.03002, lon=82.92002)) is None
    assert geo.reverse_calls == 1


# --- API ---


@pytest.fixture
def geo() -> StubGeocoder:
    return StubGeocoder(
        [place("osm-W1", "Аура", subtitle="Военная улица, 5", kind=PlaceKind.PLACE)]
    )


@pytest.fixture
def client(geo: StubGeocoder) -> TestClient:
    app = create_app(
        Settings(transit_feed="fake"), geocoder=geo, clock=ManualClock(), start_poller=False
    )
    return TestClient(app)


def test_api_search(client: TestClient) -> None:
    response = client.get("/api/v1/search", params={"q": "аура"})
    assert response.status_code == 200
    assert response.json() == {
        "places": [
            {
                "id": "osm-W1",
                "title": "Аура",
                "subtitle": "Военная улица, 5",
                "kind": "place",
                "point": {"lat": 55.03, "lon": 82.92},
            }
        ]
    }


def test_api_search_too_short_is_422(client: TestClient) -> None:
    assert client.get("/api/v1/search", params={"q": "ле"}).status_code == 422


def test_api_search_unavailable_is_503_in_russian(client: TestClient, geo: StubGeocoder) -> None:
    geo.fail = True
    response = client.get("/api/v1/search", params={"q": "аура"})
    assert response.status_code == 503
    assert response.json() == {
        "code": "GEOCODER_UNAVAILABLE",
        "message": "Поиск адресов сейчас не работает. Выберите точку на карте.",
    }


def test_api_reverse(client: TestClient, geo: StubGeocoder) -> None:
    geo.reverse_result = place("osm-N2", "Цирк", kind=PlaceKind.STOP)
    response = client.get("/api/v1/search/reverse", params={"lat": 55.03, "lon": 82.92})
    assert response.status_code == 200
    assert response.json()["place"]["title"] == "Цирк"


def test_api_reverse_nothing_near(client: TestClient) -> None:
    response = client.get("/api/v1/search/reverse", params={"lat": 55.03, "lon": 82.92})
    assert response.json() == {"place": None}


def test_api_reverse_outside_city(client: TestClient, geo: StubGeocoder) -> None:
    response = client.get("/api/v1/search/reverse", params={"lat": 56.5, "lon": 84.9})
    assert response.status_code == 422
    assert response.json()["code"] == "OUTSIDE_CITY"
    assert "56.5" not in response.text
    assert geo.reverse_calls == 0
