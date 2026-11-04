"""Разбор ответов Photon на сохранённых образцах (сняты 2026-11-04)."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.adapters.photon.parse import PhotonFormatError, parse_feature, parse_features
from app.domain.models import PlaceKind

SAMPLES = Path(__file__).parent / "photon_samples"


def load(name: str) -> Any:
    return json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def test_mall_has_name_and_address() -> None:
    [aura] = parse_features(load("search_aura"))
    assert aura.title == "Аура"
    assert aura.subtitle == "Военная улица, 5, Депутатский"
    assert aura.kind is PlaceKind.PLACE
    assert 55.0 < aura.point.lat < 55.1
    assert 82.9 < aura.point.lon < 83.0  # [lon, lat] в GeoJSON перевёрнут правильно
    assert aura.id.startswith("osm-")


def test_house_without_name_shows_address_as_title() -> None:
    [house] = parse_features(load("search_krasny25"))
    assert house.title == "Красный проспект, 25/1"  # дробный номер сохраняется
    assert house.kind is PlaceKind.ADDRESS
    assert house.subtitle == "Депутатский"


def test_bus_stop_is_stop() -> None:
    [stop] = parse_features(load("search_tsirk"))
    assert stop.title == "Цирк"
    assert stop.kind is PlaceKind.STOP


def test_street() -> None:
    items = parse_features(load("search_vokzal"))
    assert {i.kind for i in items} == {PlaceKind.STREET}
    assert items[0].title == "Вокзальная магистраль"


def test_empty_result() -> None:
    assert parse_features(load("search_empty")) == []


def test_reverse_samples() -> None:
    [square] = parse_features(load("reverse_station"))
    assert square.title == "Площадь Гарина-Михайловского"
    [kiosk] = parse_features(load("reverse_house"))
    assert kiosk.subtitle is not None
    assert "12/1" in kiosk.subtitle


@pytest.mark.parametrize(
    "feature",
    [
        None,
        {},
        {"properties": {"name": "X"}},
        {"properties": {"name": "X"}, "geometry": {"type": "Point", "coordinates": [82.9]}},
        {"properties": {"name": "X"}, "geometry": {"type": "Point", "coordinates": ["a", "b"]}},
        {"properties": {}, "geometry": {"type": "Point", "coordinates": [82.9, 55.0]}},
        {"properties": {"name": "X"}, "geometry": {"type": "Point", "coordinates": [82.9, 155]}},
    ],
)
def test_broken_feature_is_skipped(feature: Any) -> None:
    assert parse_feature(feature) is None


def test_broken_feature_does_not_break_the_rest() -> None:
    body = load("search_aura")
    body["features"].insert(0, {"type": "Feature"})
    assert [i.title for i in parse_features(body)] == ["Аура"]


@pytest.mark.parametrize("body", [None, [], {"type": "FeatureCollection"}, {"features": "x"}])
def test_not_geojson_raises(body: Any) -> None:
    with pytest.raises(PhotonFormatError):
        parse_features(body)
