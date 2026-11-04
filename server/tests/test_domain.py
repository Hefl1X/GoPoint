from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from app.domain.models import (
    Accessibility,
    Bounds,
    EtaDiagnostics,
    EtaMethod,
    LatLon,
    Leg,
    Line,
    Place,
    Stop,
    TransportType,
    WalkLeg,
)

NOW = datetime(2026, 11, 4, 5, 27, tzinfo=UTC)


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


def test_leg_discriminated_by_kind() -> None:
    adapter: TypeAdapter[Leg] = TypeAdapter(Leg)
    stop = Stop(id="1", name="Цирк", point=LatLon(lat=55.04, lon=82.92))
    transit = adapter.validate_python(
        {
            "kind": "transit",
            "vehicleId": "v1",
            "line": Line(id="1-3", type=TransportType.BUS, number="3", title="3").model_dump(),
            "lowFloor": "unknown",
            "boardStop": stop.model_dump(),
            "alightStop": stop.model_dump(),
            "waitS": 120,
            "departAt": NOW,
            "arriveAt": NOW,
            "diagnostics": EtaDiagnostics(
                method=EtaMethod.DISTANCE, position_observed_at=NOW
            ).model_dump(),
        }
    )
    assert transit.kind == "transit"
    assert transit.low_floor is Accessibility.UNKNOWN

    walk = adapter.validate_python(
        WalkLeg(
            origin=Place(point=stop.point),
            destination=Place(point=stop.point),
            distance_m=0,
            duration_s=0,
        ).model_dump(by_alias=True)
    )
    assert walk.kind == "walk"


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
