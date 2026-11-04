"""Разбор ответа OpenTripPlanner 2.10 (GTFS GraphQL API, planConnection). Чистые функции.

Поля из схемы OTP 2.10.0:
application/src/main/resources/org/opentripplanner/apis/gtfs/schema.graphqls
Линия участка приходит в формате Google Encoded Polyline (порядок lat, lon).
"""

from __future__ import annotations

from typing import Any

from app.domain.models import LatLon, Place, WalkLeg
from app.ports import (
    NoWalkRouteError,
    PointNotOnStreetError,
    WalkPlannerError,
    WalkPlannerUnavailableError,
)

# Безымянные шаги, которые OTP называет по типу пути (bogusName = true).
_STAIRS_NAMES = {"steps", "escalator"}

# Коды RoutingErrorCode, которые значат «точку не привязать к улице».
_NOT_ON_STREET = {"LOCATION_NOT_FOUND", "OUTSIDE_BOUNDS"}


def decode_polyline(encoded: str) -> list[LatLon]:
    """Google Encoded Polyline → точки (https://developers.google.com/maps/documentation/utilities/polylinealgorithm)."""
    points: list[LatLon] = []
    index = lat = lon = 0
    length = len(encoded)
    while index < length:
        deltas: list[int] = []
        for _ in range(2):
            shift = result = 0
            while True:
                if index >= length:
                    raise ValueError("линия оборвана")
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        points.append(LatLon(lat=lat / 1e5, lon=lon / 1e5))
    return points


def parse_walk(body: Any, origin: Place, destination: Place) -> WalkLeg:
    """Пеший участок из ответа planConnection или понятная ошибка."""
    if not isinstance(body, dict):
        raise WalkPlannerUnavailableError("OTP: ответ не JSON-объект")
    if body.get("errors"):
        raise WalkPlannerUnavailableError("OTP: ошибка запроса GraphQL")
    plan = (body.get("data") or {}).get("planConnection")
    if not isinstance(plan, dict):
        raise WalkPlannerUnavailableError("OTP: нет planConnection")

    codes = {e.get("code") for e in plan.get("routingErrors") or [] if isinstance(e, dict)}
    if codes & _NOT_ON_STREET:
        raise PointNotOnStreetError(", ".join(sorted(str(c) for c in codes)))

    edges = plan.get("edges") or []
    if not edges:
        raise NoWalkRouteError(", ".join(sorted(str(c) for c in codes)) or "нет вариантов")
    node = edges[0].get("node") if isinstance(edges[0], dict) else None
    if not isinstance(node, dict):
        raise WalkPlannerUnavailableError("OTP: вариант без данных")

    try:
        legs = node.get("legs") or []
        geometry: list[LatLon] = []
        distance = 0.0
        has_stairs = False
        for leg in legs:
            for step in leg.get("steps") or []:
                if step.get("bogusName") and step.get("streetName") in _STAIRS_NAMES:
                    has_stairs = True
            distance += float(leg.get("distance") or 0)
            points = (leg.get("legGeometry") or {}).get("points")
            if isinstance(points, str) and points:
                part = decode_polyline(points)
                # Стык участков: одна и та же точка дважды не нужна.
                if geometry and part and geometry[-1] == part[0]:
                    part = part[1:]
                geometry.extend(part)
        climb, descent = node.get("elevationGained"), node.get("elevationLost")
        return WalkLeg(
            origin=origin,
            destination=destination,
            distance_m=round(distance),
            duration_s=round(float(node["duration"])),
            geometry=geometry,
            climb_m=round(float(climb), 1) if climb is not None else None,
            descent_m=round(float(descent), 1) if descent is not None else None,
            has_stairs=has_stairs,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WalkPlannerError(f"OTP: непонятный вариант ({type(exc).__name__})") from exc
