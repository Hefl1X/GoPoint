"""Разбор ответов Photon (GeoJSON). Чистые функции, тесты на образцах.

Поля описаны в https://github.com/komoot/photon/blob/master/docs/api-v1.md
(проверено 2026-11-04, Photon 1.3.0). Порядок координат в GeoJSON [lon, lat]
известен только здесь.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from app.domain.models import LatLon, PlaceKind, PlaceSuggestion

log = logging.getLogger(__name__)


class PhotonFormatError(ValueError):
    """Ответ Photon не похож на GeoJSON FeatureCollection."""


# Остановки транспорта в OpenStreetMap (основной тег объекта).
_STOP_TAGS = {
    ("highway", "bus_stop"),
    ("highway", "platform"),
    ("public_transport", "platform"),
    ("public_transport", "stop_position"),
    ("public_transport", "station"),
    ("railway", "tram_stop"),
    ("railway", "station"),
    ("railway", "halt"),
    ("railway", "subway_entrance"),
    ("amenity", "bus_station"),
}
_AREA_TYPES = {"district", "locality", "city", "county", "state", "country"}


def _text(props: dict[str, Any], key: str) -> str | None:
    value = props.get(key)
    if isinstance(value, str | int) and str(value).strip():
        return " ".join(str(value).split())
    return None


def _kind(props: dict[str, Any], has_name: bool) -> PlaceKind:
    key, value, ptype = props.get("osm_key"), props.get("osm_value"), props.get("type")
    if (key, value) in _STOP_TAGS:
        return PlaceKind.STOP
    if ptype == "street":
        return PlaceKind.STREET
    if ptype in _AREA_TYPES or (key == "place" and value != "house"):
        return PlaceKind.AREA
    if not has_name:
        return PlaceKind.ADDRESS
    return PlaceKind.PLACE


def _address(props: dict[str, Any]) -> str | None:
    street, number = _text(props, "street"), _text(props, "housenumber")
    if street and number:
        return f"{street}, {number}"
    return street


def parse_feature(feature: Any) -> PlaceSuggestion | None:
    """Одна подсказка или None, если запись неполная (такие пропускаем)."""
    if not isinstance(feature, dict):
        return None
    props, geometry = feature.get("properties"), feature.get("geometry")
    if not isinstance(props, dict) or not isinstance(geometry, dict):
        return None
    coords = geometry.get("coordinates")
    if geometry.get("type") != "Point" or not isinstance(coords, list) or len(coords) < 2:
        return None

    name = _text(props, "name")
    address = _address(props)
    district, city = _text(props, "district"), _text(props, "city")
    locality = _text(props, "locality")
    if name:
        title, first = name, address
    elif address:
        title, first = address, None
    else:
        return None
    area = district or locality
    subtitle_parts = [p for p in (first, area) if p and p != title]
    if not subtitle_parts and city and city != title:
        subtitle_parts = [city]

    try:
        point = LatLon(lat=float(coords[1]), lon=float(coords[0]))
        return PlaceSuggestion(
            id=f"osm-{props.get('osm_type', '')}{props.get('osm_id', '')}",
            title=title,
            subtitle=", ".join(subtitle_parts) or None,
            kind=_kind(props, has_name=name is not None),
            point=point,
        )
    except (TypeError, ValueError, ValidationError):
        return None


def parse_features(body: Any) -> list[PlaceSuggestion]:
    """Все подсказки из ответа /api или /reverse. Битые записи пропускаются."""
    if not isinstance(body, dict) or not isinstance(body.get("features"), list):
        raise PhotonFormatError("нет списка features")
    result: list[PlaceSuggestion] = []
    skipped = 0
    for feature in body["features"]:
        item = parse_feature(feature)
        if item is None:
            skipped += 1
        else:
            result.append(item)
    if skipped:
        log.info("Photon: пропущено записей без имени или координат: %d", skipped)
    return result
