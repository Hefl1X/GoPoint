"""GraphQL-порт OTP выбирает один фид и сохраняет идентичность рейса."""

import json
from datetime import date, datetime
from typing import Any

import httpx
import pytest

from app.adapters.otp.transit import OtpTransitPlanner
from app.adapters.otp.transit_parse import LOW_FEED, parse_plan, parse_timetable
from app.domain.low_floor import TripOccurrence
from app.domain.models import LatLon, Place, TransportType
from app.domain.trip_plan import PlannedWalk, TripSegment
from app.ports import TransitPlannerUnavailableError

DAY = date(2026, 11, 24)
AFTER_MIDNIGHT = "2026-11-25T00:05:00+07:00"
ESTIMATE = "2026-11-25T00:07:00+07:00"
ARRIVE = "2026-11-25T00:20:00+07:00"
AT = datetime.fromisoformat("2026-11-24T23:50:00+07:00")
A = Place(point=LatLon(lat=55.0, lon=83.0))
B = Place(point=LatLon(lat=55.1, lon=83.1))
OCCURRENCE = TripOccurrence("night", DAY)


def _feeds(version: str = "graph") -> list[dict[str, str]]:
    return [
        {"feedId": "gopoint-all", "version": "graph"},
        {"feedId": "gopoint-low", "version": version},
    ]


def _leg(*, estimate: str | None = ESTIMATE) -> dict[str, Any]:
    stop = {
        **{"lat": 55.0, "lon": 83.0, "name": "Остановка"},
        "gtfsId": "gopoint-low:same-stop",
    }
    return {
        "mode": "BUS",
        "transitLeg": True,
        "distance": 2000,
        "serviceDate": DAY.isoformat(),
        "from": {**stop, "stop": stop, "stopPosition": {"position": 2}},
        "to": {**stop, "stop": stop, "stopPosition": {"position": 4}},
        "start": {
            "scheduledTime": AFTER_MIDNIGHT,
            "estimated": {"time": estimate} if estimate else None,
        },
        "end": {"scheduledTime": ARRIVE, "estimated": None},
        "headsign": None,
        "route": {"gtfsId": "gopoint-low:minibus-24", "shortName": "24", "longName": None},
        "trip": {"gtfsId": "gopoint-low:night"},
        "legGeometry": {"points": "_p~iF~ps|U_ulLnnqC"},
        "steps": None,
    }


def _response(
    legs: list[dict[str, Any]], *, version: str = "graph", errors: list[str] | None = None
) -> dict[str, object]:
    return {
        "data": {
            "feeds": _feeds(version),
            "planConnection": {
                "routingErrors": [{"code": code} for code in errors or []],
                "edges": [{"node": {"legs": legs}}] if legs else [],
            },
        }
    }


def _planner(transport: httpx.MockTransport) -> OtpTransitPlanner:
    return OtpTransitPlanner(
        base_url="http://otp:8080/",
        speed_mps=1.3,
        board_slack_s=30,
        transfer_slack_s=60,
        horizon_min=60,
        transport=transport,
    )


async def test_request_isolates_profile_and_preserves_night_boarding() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/otp/gtfs/v1"
        body = json.loads(request.content)
        assert body["variables"]["agency"] == "gopoint-low:tsugaet"
        assert body["variables"]["departure"] == AT.isoformat()
        assert body["variables"]["window"] == "60m"
        return httpx.Response(200, json=_response([_leg()]))

    planner = _planner(httpx.MockTransport(handle))
    try:
        result = await planner.plan(A, B, at=AT, low_floor_only=True)
    finally:
        await planner.aclose()
    assert result.graph_version == "graph"
    (journey,) = result.journeys
    (ride,) = journey.rides
    assert ride.segment == TripSegment(OCCURRENCE, 2, 4)
    assert ride.board_stop.id == ride.alight_stop.id == "same-stop"
    assert ride.depart_at == datetime.fromisoformat(ESTIMATE)
    assert ride.arrive_at == datetime.fromisoformat(ARRIVE)
    assert ride.time_source == "realtime"
    assert ride.line.type is TransportType.MINIBUS
    assert len(ride.geometry) == 2


def test_unversioned_walking_and_expired_calendar_are_distinct_from_transport() -> None:
    walk = {
        **_leg(),
        "mode": "WALK",
        "transitLeg": False,
        "route": None,
        "trip": None,
        "serviceDate": None,
        "steps": [{"streetName": "steps", "bogusName": True}],
    }
    result = parse_plan(
        json.dumps(_response([walk], version="old", errors=["OUTSIDE_SERVICE_PERIOD"])).encode(),
        LOW_FEED,
    )
    assert result.graph_version is None
    assert result.routing_errors == {"OUTSIDE_SERVICE_PERIOD"}
    (leg,) = result.journeys[0].legs
    assert isinstance(leg, PlannedWalk) and leg.leg.has_stairs
    assert not result.journeys[0].rides


def test_response_with_transit_from_other_feed_is_rejected() -> None:
    leg = _leg()
    leg["trip"]["gtfsId"] = "gopoint-all:night"
    with pytest.raises(TransitPlannerUnavailableError):
        parse_plan(json.dumps(_response([leg])).encode(), LOW_FEED)


@pytest.mark.parametrize(
    "body",
    [b"not json", b'{"errors":[{"message":"invalid query"}]}', b'{"data":{"feeds":[]}}'],
)
def test_invalid_response_is_distinct_from_empty_plan(body: bytes) -> None:
    with pytest.raises(TransitPlannerUnavailableError):
        parse_plan(body, LOW_FEED)
    result = parse_plan(json.dumps(_response([])).encode(), LOW_FEED)
    assert result.graph_version == "graph" and result.journeys == ()


async def test_lookup_uses_exact_occurrence_and_keeps_repeated_stops() -> None:
    def call(time: str, *, estimate: str | None = None) -> dict[str, object]:
        return {
            "stopLocation": {"gtfsId": "gopoint-low:same-stop"},
            "schedule": {"time": {"arrival": time, "departure": time}},
            "realTime": {"arrival": None, "departure": {"time": estimate}} if estimate else None,
        }

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["variables"] == {"trip": "gopoint-low:night", "date": DAY.isoformat()}
        return httpx.Response(
            200,
            json={
                "data": {
                    "feeds": _feeds(),
                    "trip": {
                        "gtfsId": "gopoint-low:night",
                        "onServiceDate": {
                            "serviceDate": DAY.isoformat(),
                            "realTimeTripState": {"canceled": True},
                            "stopCalls": [call(AFTER_MIDNIGHT, estimate=ESTIMATE), call(ARRIVE)],
                        },
                    },
                }
            },
        )

    planner = _planner(httpx.MockTransport(handle))
    try:
        result = await planner.timetable(OCCURRENCE, low_floor_only=True)
    finally:
        await planner.aclose()
    assert result.graph_version == "graph" and result.timetable is not None
    assert result.timetable.canceled
    first, last = result.timetable.calls
    assert first.stop_id == last.stop_id
    assert first.arrive_at == datetime.fromisoformat(AFTER_MIDNIGHT)
    assert first.depart_at == datetime.fromisoformat(ESTIMATE) and first.time_source == "realtime"
    assert last.depart_at == datetime.fromisoformat(ARRIVE) and last.time_source == "scheduled"


def test_missing_trip_is_a_valid_lookup_response() -> None:
    result = parse_timetable(
        json.dumps({"data": {"feeds": _feeds(), "trip": None}}).encode(), LOW_FEED, OCCURRENCE
    )
    assert result.graph_version == "graph" and result.timetable is None
