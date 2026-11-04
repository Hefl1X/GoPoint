"""WalkPlanner на OpenTripPlanner 2.10 (контейнер otp во внутренней сети).

Только пешие участки (без транспорта): directOnly + WALK. Профиль коляски включён
всегда, здесь, на сервере (wheelchair.enabled = true); пользователь его не выбирает.
Что он делает (docs Accessibility.md, RouteRequest.md OTP 2.10): обходит лестницы,
дороги с wheelchair=no и высокие бордюры (barrier=kerb без kerb=flush/lowered/no),
штрафует уклон круче maxSlope (8,3 %). Это штрафы, а не запрет: если другого пути нет,
OTP может провести и через них. Настройки штрафов: otp/router-config.json.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.adapters.otp.parse import parse_walk
from app.domain.models import Place, WalkLeg
from app.ports import NoAccessibleWalkError, NoWalkRouteError, WalkPlannerUnavailableError

GRAPHQL_PATH = "/otp/gtfs/v1"

QUERY = """
query Walk($from: PlanLabeledLocationInput!, $to: PlanLabeledLocationInput!, $speed: Speed!) {
  planConnection(
    origin: $from
    destination: $to
    first: 1
    modes: { directOnly: true, direct: [WALK] }
    preferences: {
      accessibility: { wheelchair: { enabled: true } }
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
        try:
            return await self._plan(QUERY, origin, destination)
        except NoAccessibleWalkError:
            raise
        except NoWalkRouteError as exc:
            # Есть ли путь хотя бы для обычного пешехода? Тогда мешают лестницы или
            # препятствия: человеку нужно сказать именно это. Этот путь мы не отдаём.
            try:
                await self._plan(
                    QUERY.replace("enabled: true", "enabled: false"), origin, destination
                )
            except NoWalkRouteError:
                raise exc from None
            raise NoAccessibleWalkError("путь есть только с препятствиями") from exc

    async def _plan(self, query: str, origin: Place, destination: Place) -> WalkLeg:
        payload = {
            "query": query,
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
