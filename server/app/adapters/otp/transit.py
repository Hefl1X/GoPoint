"""Поездки с транспортом, ходьбой и пересадками через GTFS GraphQL OTP."""

from datetime import datetime

import httpx

from app.adapters.otp.transit_parse import ALL_FEED, LOW_FEED, parse_plan, parse_timetable
from app.adapters.otp.walk import GRAPHQL_PATH, location_input
from app.domain.gtfs import AGENCY_ID
from app.domain.low_floor import TripOccurrence
from app.domain.models import Place
from app.domain.trip_plan import TripLookup, TripPlan
from app.ports import TransitPlannerUnavailableError

PLAN_QUERY = """
query PlanJourney(
  $from: PlanLabeledLocationInput!, $to: PlanLabeledLocationInput!,
  $departure: OffsetDateTime!, $window: Duration!, $agency: String!,
  $speed: Speed!, $boardSlack: Duration!, $transferSlack: Duration!
) {
  feeds { feedId version }
  planConnection(
    origin: $from, destination: $to, dateTime: {earliestDeparture: $departure}
    searchWindow: $window, first: 8
    modes: {direct: [WALK], transit: {access: [WALK], egress: [WALK], transfer: [WALK]}}
    preferences: {
      transit: {
        filters: [{include: [{agencies: [$agency]}]}]
        board: {slack: $boardSlack}
        transfer: {slack: $transferSlack, maximumTransfers: 2}
        timetable: {
          excludeRealTimeUpdates: false
          includeRealTimeCancellations: false
          includePlannedCancellations: false
        }
      }
      street: {walk: {speed: $speed}}
      accessibility: {wheelchair: {enabled: false}}
    }
  ) {
    routingErrors { code }
    edges { node { legs {
      mode transitLeg distance serviceDate headsign
      from { ...JourneyPlace } to { ...JourneyPlace }
      start { ...JourneyTime } end { ...JourneyTime }
      route { gtfsId shortName longName }
      trip { gtfsId }
      legGeometry { points }
      steps { streetName bogusName }
    } } }
  }
}

fragment JourneyPlace on Place {
  lat lon name
  stop { gtfsId lat lon name }
  stopPosition { ... on PositionAtStop { position } }
}

fragment JourneyTime on LegTime {
  scheduledTime estimated { time }
}
"""

TIMETABLE_QUERY = """
query Timetable($trip: String!, $date: LocalDate!) {
  feeds { feedId version }
  trip(id: $trip) {
    gtfsId
    onServiceDate(date: $date) {
      serviceDate
      realTimeTripState { canceled }
      stopCalls {
        stopLocation { ... on Stop { gtfsId } }
        schedule { time { ... on ArrivalDepartureTime { arrival departure } } }
        realTime { arrival { time } departure { time } }
      }
    }
  }
}
"""


class OtpTransitPlanner:
    def __init__(
        self,
        *,
        base_url: str,
        speed_mps: float,
        board_slack_s: int,
        transfer_slack_s: int,
        horizon_min: int,
        timeout_s: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout_s, transport=transport, trust_env=False
        )
        self._speed_mps = speed_mps
        self._board_slack_s = board_slack_s
        self._transfer_slack_s = transfer_slack_s
        self._horizon_min = horizon_min

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _query(self, query: str, variables: dict[str, object]) -> bytes:
        try:
            response = await self._client.post(
                GRAPHQL_PATH, json={"query": query, "variables": variables}
            )
        except httpx.HTTPError as exc:
            raise TransitPlannerUnavailableError("OTP не ответил на запрос") from exc
        if response.status_code != httpx.codes.OK:
            raise TransitPlannerUnavailableError(f"OTP вернул HTTP {response.status_code}")
        return response.content

    async def plan(
        self, origin: Place, destination: Place, *, at: datetime, low_floor_only: bool
    ) -> TripPlan:
        feed = LOW_FEED if low_floor_only else ALL_FEED
        body = await self._query(
            PLAN_QUERY,
            {
                "from": location_input(origin),
                "to": location_input(destination),
                "departure": at.isoformat(),
                "window": f"{self._horizon_min}m",
                "agency": f"{feed}:{AGENCY_ID}",
                "speed": self._speed_mps,
                "boardSlack": f"{self._board_slack_s}s",
                "transferSlack": f"{self._transfer_slack_s}s",
            },
        )
        return parse_plan(body, feed)

    async def timetable(self, occurrence: TripOccurrence, *, low_floor_only: bool) -> TripLookup:
        feed = LOW_FEED if low_floor_only else ALL_FEED
        body = await self._query(
            TIMETABLE_QUERY,
            {"trip": f"{feed}:{occurrence.trip_id}", "date": occurrence.service_date.isoformat()},
        )
        return parse_timetable(body, feed, occurrence)
