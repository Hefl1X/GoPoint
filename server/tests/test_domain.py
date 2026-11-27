import pytest
from pydantic import ValidationError

from app.config import Settings
from app.domain.models import (
    Accessibility,
    Bounds,
    LatLon,
    Place,
    TransportType,
    WalkLeg,
)


def test_latlon_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        LatLon(lat=91, lon=0)
    with pytest.raises(ValidationError):
        LatLon(lat=0, lon=181)


def test_latlon_serializes_as_object() -> None:
    assert LatLon(lat=55.03, lon=82.92).model_dump() == {"lat": 55.03, "lon": 82.92}


def test_bounds_contains() -> None:
    city = Bounds(south_west=LatLon(lat=54.8, lon=82.7), north_east=LatLon(lat=55.2, lon=83.2))
    assert city.contains(LatLon(lat=55.03, lon=82.92))
    assert not city.contains(LatLon(lat=55.75, lon=37.62))


def test_accessibility_has_three_states() -> None:
    assert {a.value for a in Accessibility} == {"yes", "no", "unknown"}


def test_json_uses_camel_case() -> None:
    walk = WalkLeg(
        origin=Place(point=LatLon(lat=55, lon=82.9)),
        destination=Place(point=LatLon(lat=55, lon=82.9)),
        distance_m=10,
        duration_s=12,
    )
    dumped = walk.model_dump(by_alias=True)
    assert "distanceM" in dumped
    assert "durationS" in dumped


def test_all_four_transport_types_polled_by_default() -> None:
    # Маршрутки включены решением владельца 4 ноября 2026.
    assert Settings().transport_type_set == frozenset(TransportType)
