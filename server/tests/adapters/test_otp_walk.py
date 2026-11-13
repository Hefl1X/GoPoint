"""Адаптер OpenTripPlanner для пеших участков (без сети)."""

import json
from typing import Any

import httpx
import pytest

from app.adapters.otp.parse import decode_polyline, parse_walk
from app.adapters.otp.walk import GRAPHQL_PATH, OtpWalkPlanner
from app.domain.models import LatLon, Place
from app.ports import (
    NoWalkRouteError,
    PointNotOnStreetError,
    WalkPlannerError,
    WalkPlannerUnavailableError,
)

A = Place(point=LatLon(lat=55.03, lon=82.92))
B = Place(point=LatLon(lat=55.04, lon=82.93))


def test_decode_polyline_google_example() -> None:
    # Пример из описания формата Google.
    points = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert [(p.lat, p.lon) for p in points] == [
        (38.5, -120.2),
        (40.7, -120.95),
        (43.252, -126.453),
    ]


def test_decode_broken_polyline() -> None:
    with pytest.raises(ValueError, match="оборвана"):
        decode_polyline("_p~iF~ps|U_")


def plan(edges: list[Any], errors: list[str] | None = None) -> dict[str, Any]:
    return {
        "data": {
            "planConnection": {
                "routingErrors": [{"code": c} for c in errors or []],
                "edges": edges,
            }
        }
    }


def node(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "duration": 754,
        "elevationGained": 3.24,
        "elevationLost": 1.0,
        "legs": [
            {"mode": "WALK", "distance": 600.4, "legGeometry": {"points": "_p~iF~ps|U_ulLnnqC"}},
        ],
    }
    base.update(kw)
    return {"node": base}


def test_parse_walk() -> None:
    leg = parse_walk(plan([node()]), A, B)
    assert leg.duration_s == 754
    assert leg.distance_m == 600
    assert leg.climb_m == 3.2
    assert leg.descent_m == 1.0
    assert len(leg.geometry) == 2
    assert leg.origin == A


def test_parse_walk_joins_legs_without_duplicate_point() -> None:
    legs = [
        {"distance": 10, "legGeometry": {"points": "_p~iF~ps|U_ulLnnqC"}},
        {"distance": 5, "legGeometry": {"points": "_flwFn`faV_mqNvxq`@"}},
    ]
    leg = parse_walk(plan([node(legs=legs)]), A, B)
    assert leg.distance_m == 15
    assert len(leg.geometry) == 3


def test_no_elevation_is_none() -> None:
    leg = parse_walk(plan([node(elevationGained=None, elevationLost=None)]), A, B)
    assert leg.climb_m is None


@pytest.mark.parametrize("code", ["LOCATION_NOT_FOUND", "OUTSIDE_BOUNDS"])
def test_point_not_on_street(code: str) -> None:
    with pytest.raises(PointNotOnStreetError):
        parse_walk(plan([], [code]), A, B)


def test_no_route() -> None:
    with pytest.raises(NoWalkRouteError):
        parse_walk(plan([], ["NO_DIRECT_MODE_CONNECTION"]), A, B)


@pytest.mark.parametrize(
    "body",
    [None, [], {"errors": [{"message": "x"}]}, {"data": {}}, {"data": {"planConnection": 1}}],
)
def test_broken_answer_is_unavailable(body: Any) -> None:
    with pytest.raises(WalkPlannerUnavailableError):
        parse_walk(body, A, B)


def test_broken_itinerary() -> None:
    with pytest.raises(WalkPlannerError):
        parse_walk(plan([node(duration="много")]), A, B)


async def test_adapter_sends_plain_walk_only_request() -> None:
    seen: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == GRAPHQL_PATH
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=plan([node()]))

    planner = OtpWalkPlanner(
        base_url="http://otp.test", speed_mps=0.8, transport=httpx.MockTransport(handle)
    )
    leg = await planner.walk(A, B)
    await planner.aclose()
    assert leg.duration_s == 754
    query, variables = seen[0]["query"], seen[0]["variables"]
    # Обычный пешеход (решение владельца 14.11): режим коляски выключен явно, чтобы
    # на него не влияли настройки по умолчанию в router-config.json. Только пешком.
    assert "wheelchair: { enabled: false }" in query
    assert "enabled: true" not in query
    assert "directOnly: true, direct: [WALK]" in query
    assert variables["speed"] == 0.8
    assert variables["from"]["location"]["coordinate"] == {"latitude": 55.03, "longitude": 82.92}


@pytest.mark.parametrize("response", [httpx.Response(500), httpx.Response(200, text="<html>")])
async def test_adapter_bad_http(response: httpx.Response) -> None:
    planner = OtpWalkPlanner(
        base_url="http://otp.test",
        speed_mps=0.8,
        transport=httpx.MockTransport(lambda _r: response),
    )
    with pytest.raises(WalkPlannerUnavailableError):
        await planner.walk(A, B)
    await planner.aclose()


async def test_adapter_timeout() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    planner = OtpWalkPlanner(
        base_url="http://otp.test", speed_mps=0.8, transport=httpx.MockTransport(handle)
    )
    with pytest.raises(WalkPlannerUnavailableError):
        await planner.walk(A, B)
    await planner.aclose()


async def test_no_route_at_all_asks_once() -> None:
    answer = plan([], ["NO_DIRECT_MODE_CONNECTION"])
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=answer)

    planner = OtpWalkPlanner(
        base_url="http://otp.test", speed_mps=0.8, transport=httpx.MockTransport(handle)
    )
    with pytest.raises(NoWalkRouteError):
        await planner.walk(A, B)
    assert len(calls) == 1  # повторного запроса «для пешехода» больше нет
    await planner.aclose()


def test_stairs_are_flagged() -> None:
    legs = [
        {
            "distance": 50,
            "legGeometry": {"points": "_p~iF~ps|U_ulLnnqC"},
            "steps": [
                {"streetName": "Красный проспект", "bogusName": False},
                {"streetName": "steps", "bogusName": True},
            ],
        }
    ]
    assert parse_walk(plan([node(legs=legs)]), A, B).has_stairs
    assert not parse_walk(plan([node()]), A, B).has_stairs


def test_street_named_like_stairs_is_not_stairs() -> None:
    legs = [{"distance": 5, "steps": [{"streetName": "steps", "bogusName": False}]}]
    assert not parse_walk(plan([node(legs=legs)]), A, B).has_stairs
