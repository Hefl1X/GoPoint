"""WalkPlanner на OpenTripPlanner 2.10 (контейнер otp во внутренней сети).

Только пешие участки (без транспорта): directOnly + WALK, обычный пешеход.
Режим коляски выключен явно (wheelchair.enabled = false) по решению владельца 14.11.2026:
в OpenStreetMap Новосибирска бордюры и съезды почти не размечены, поэтому путь строится
по всем улицам и тротуарам. Ступени на пути видны по признаку hasStairs (parse.py).
Скорость задаётся настройкой GOPOINT_WALK_SPEED_MPS.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.adapters.otp.parse import parse_walk
from app.domain.models import Place, WalkLeg
from app.ports import WalkPlannerUnavailableError

GRAPHQL_PATH = "/otp/gtfs/v1"

QUERY = """
query Walk($from: PlanLabeledLocationInput!, $to: PlanLabeledLocationInput!, $speed: Speed!) {
  planConnection(
    origin: $from
    destination: $to
    first: 1
    modes: { directOnly: true, direct: [WALK] }
    preferences: {
      accessibility: { wheelchair: { enabled: false } }
      street: { walk: { speed: $speed } }
    }
  ) {
    routingErrors { code }
    edges {
      node {
        duration
        elevationGained
        elevationLost
        legs { mode distance legGeometry { points } steps { streetName bogusName } }
      }
    }
  }
}
"""


def _location(place: Place) -> dict[str, Any]:
    return {"location": {"coordinate": {"latitude": place.point.lat, "longitude": place.point.lon}}}


class OtpWalkPlanner:
    def __init__(
        self,
        *,
        base_url: str,
        speed_mps: float,
        timeout_s: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            headers={"Content-Type": "application/json"},
            transport=transport,
        )
        self._speed_mps = speed_mps

    async def aclose(self) -> None:
        await self._client.aclose()

    async def walk(self, origin: Place, destination: Place) -> WalkLeg:
        payload = {
            "query": QUERY,
            "variables": {
                "from": _location(origin),
                "to": _location(destination),
                "speed": self._speed_mps,
            },
        }
        try:
            response = await self._client.post(GRAPHQL_PATH, json=payload)
        except httpx.TimeoutException as exc:
            raise WalkPlannerUnavailableError("OTP: нет ответа вовремя") from exc
        except httpx.HTTPError as exc:
            raise WalkPlannerUnavailableError(f"OTP: нет связи ({type(exc).__name__})") from exc
        if response.status_code != httpx.codes.OK:
            raise WalkPlannerUnavailableError(f"OTP: код {response.status_code}")
        try:
            body: Any = response.json()
        except ValueError as exc:
            raise WalkPlannerUnavailableError("OTP: ответ не JSON") from exc
        return parse_walk(body, origin, destination)
