"""Перевод ответа GTFS GraphQL 2.10 в модели поездки и расписания."""

from __future__ import annotations

from datetime import date, datetime
from itertools import pairwise
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.adapters.otp.parse import decode_polyline
from app.domain.low_floor import TripOccurrence
from app.domain.models import LatLon, Line, Place, Stop, TransportType, WalkLeg
from app.domain.trip_plan import (
    PlannedJourney,
    PlannedRide,
    PlannedWalk,
    TimetabledCall,
    TripLookup,
    TripPlan,
    TripSegment,
    TripTimetable,
)
from app.ports import TransitPlannerUnavailableError

FeedId = Literal["gopoint-all", "gopoint-low"]
ALL_FEED: FeedId = "gopoint-all"
LOW_FEED: FeedId = "gopoint-low"
_MODES = {
    "BUS": TransportType.BUS,
    "TRAM": TransportType.TRAM,
    "TROLLEYBUS": TransportType.TROLLEYBUS,
}


class _ResponseModel(BaseModel):
    model_config = ConfigDict(strict=True, alias_generator=to_camel)


class _GraphResponse[T](_ResponseModel):
    data: T | None = None
    errors: list[object] = Field(default_factory=list)


class _Feed(_ResponseModel):
    feed_id: str
    version: str | None


class _Entity(_ResponseModel):
    gtfs_id: str


class _Point(_ResponseModel):
    lat: float
    lon: float
    name: str | None

    def as_point(self) -> LatLon:
        return LatLon(lat=self.lat, lon=self.lon)


class _Stop(_Point, _Entity):
    def as_stop(self, feed: FeedId) -> Stop:
        if not self.name:
            raise ValueError("Остановка OTP без названия")
        return Stop(id=_local_id(self.gtfs_id, feed), name=self.name, point=self.as_point())


class _Position(_ResponseModel):
    position: int | None = Field(default=None, ge=1)


class _Place(_Point):
    stop: _Stop | None
    stop_position: _Position | None

    def as_place(self) -> Place:
        return Place(name=self.name, point=self.as_point())

    def boarding(self, feed: FeedId) -> tuple[Stop, int]:
        if self.stop is None or self.stop_position is None or self.stop_position.position is None:
            raise ValueError("У посадки или высадки OTP нет остановки или позиции")
        return self.stop.as_stop(feed), self.stop_position.position


class _Estimate(_ResponseModel):
    time: AwareDatetime


class _LegTime(_ResponseModel):
    scheduled_time: AwareDatetime
    estimated: _Estimate | None

    @property
    def time(self) -> datetime:
        return self.estimated.time if self.estimated else self.scheduled_time


class _Route(_Entity):
    short_name: str = Field(min_length=1)
    long_name: str | None

    def as_line(self, feed: FeedId, mode: str) -> Line:
        line_id = _local_id(self.gtfs_id, feed)
        transport = _MODES.get(mode)
        if transport is None:
            raise ValueError("Неподдерживаемый транспортный режим OTP")
        if transport is TransportType.BUS and line_id.startswith("minibus-"):
            transport = TransportType.MINIBUS
        return Line(
            id=line_id,
            type=transport,
            number=self.short_name,
            title=self.long_name or self.short_name,
        )


class _Geometry(_ResponseModel):
    points: str | None


class _Step(_ResponseModel):
    street_name: str | None
    bogus_name: bool | None


class _Leg(_ResponseModel):
    mode: str
    transit_leg: bool
    start: _LegTime
    end: _LegTime
    origin: _Place = Field(alias="from")
    to: _Place
    distance: float = Field(ge=0, allow_inf_nan=False)
    leg_geometry: _Geometry | None
    route: _Route | None
    trip: _Entity | None
    service_date: date | None
    headsign: str | None
    steps: list[_Step] | None

    def as_leg(self, feed: FeedId) -> PlannedWalk | PlannedRide:
        depart_at, arrive_at = self.start.time, self.end.time
        if arrive_at < depart_at:
            raise ValueError("Прибытие раньше отправления")
        encoded = self.leg_geometry.points if self.leg_geometry else None
        geometry = decode_polyline(encoded) if encoded else []
        if not self.transit_leg:
            if self.mode != "WALK":
                raise ValueError("Неподдерживаемый уличный режим OTP")
            walk = WalkLeg(
                origin=self.origin.as_place(),
                destination=self.to.as_place(),
                distance_m=round(self.distance),
                duration_s=round((arrive_at - depart_at).total_seconds()),
                geometry=geometry,
                has_stairs=any(
                    step.bogus_name and step.street_name in {"steps", "escalator"}
                    for step in self.steps or []
                ),
            )
            return PlannedWalk(walk, depart_at, arrive_at)
        if self.trip is None or self.route is None or self.service_date is None:
            raise ValueError("Транспортный участок OTP без рейса")
        board, first = self.origin.boarding(feed)
        alight, last = self.to.boarding(feed)
        if first >= last:
            raise ValueError("Высадка OTP не следует за посадкой")
        return PlannedRide(
            segment=TripSegment(
                TripOccurrence(_local_id(self.trip.gtfs_id, feed), self.service_date), first, last
            ),
            line=self.route.as_line(feed, self.mode),
            board_stop=board,
            alight_stop=alight,
            depart_at=depart_at,
            arrive_at=arrive_at,
            time_source="realtime" if self.start.estimated or self.end.estimated else "scheduled",
            toward=self.headsign,
            geometry=tuple(geometry),
        )


class _Itinerary(_ResponseModel):
    legs: list[_Leg] = Field(min_length=1)


class _Edge(_ResponseModel):
    node: _Itinerary


class _RoutingError(_ResponseModel):
    code: str


class _Plan(_ResponseModel):
    routing_errors: list[_RoutingError]
    edges: list[_Edge]


class _PlanData(_ResponseModel):
    feeds: list[_Feed]
    plan_connection: _Plan


class _ScheduledTime(_ResponseModel):
    arrival: AwareDatetime | None = None
    departure: AwareDatetime | None = None


class _Schedule(_ResponseModel):
    time: _ScheduledTime | None


class _RealTime(_ResponseModel):
    arrival: _Estimate | None
    departure: _Estimate | None


class _Call(_ResponseModel):
    stop_location: _Entity
    schedule: _Schedule | None
    real_time: _RealTime | None

    def as_call(self, feed: FeedId) -> TimetabledCall:
        planned = self.schedule.time if self.schedule else None
        arrival = self.real_time.arrival if self.real_time else None
        departure = self.real_time.departure if self.real_time else None
        return TimetabledCall(
            _local_id(self.stop_location.gtfs_id, feed),
            arrival.time if arrival else planned.arrival if planned else None,
            departure.time if departure else planned.departure if planned else None,
            "realtime" if arrival or departure else "scheduled",
        )


class _TripState(_ResponseModel):
    canceled: bool


class _OnServiceDate(_ResponseModel):
    service_date: date
    real_time_trip_state: _TripState | None
    stop_calls: list[_Call]


class _Trip(_Entity):
    on_service_date: _OnServiceDate | None


class _TripData(_ResponseModel):
    feeds: list[_Feed]
    trip: _Trip | None


def _local_id(value: str, feed: FeedId) -> str:
    prefix, _, local_id = value.partition(":")
    if prefix != feed or not local_id:
        raise ValueError("Ответ OTP содержит ID из другого фида")
    return local_id


def _version(feeds: list[_Feed]) -> str | None:
    versions = {feed.feed_id: feed.version for feed in feeds}
    if len(feeds) != 2 or set(versions) != {ALL_FEED, LOW_FEED}:
        return None
    all_version = versions[ALL_FEED]
    return all_version if all_version and versions[LOW_FEED] == all_version else None


def parse_plan(body: bytes, feed: FeedId) -> TripPlan:
    try:
        response = _GraphResponse[_PlanData].model_validate_json(body)
        if response.errors or response.data is None:
            raise ValueError("OTP отклонил запрос маршрута")
        data = response.data
        journeys = []
        for edge in data.plan_connection.edges:
            legs = tuple(leg.as_leg(feed) for leg in edge.node.legs)
            if any(first.arrive_at > second.depart_at for first, second in pairwise(legs)):
                raise ValueError("Участки OTP перекрываются по времени")
            journeys.append(PlannedJourney(legs))
        codes = frozenset(item.code for item in data.plan_connection.routing_errors)
        return TripPlan(_version(data.feeds), tuple(journeys), codes)
    except ValueError as exc:
        raise TransitPlannerUnavailableError("OTP вернул непригодный ответ маршрута") from exc


def parse_timetable(body: bytes, feed: FeedId, occurrence: TripOccurrence) -> TripLookup:
    try:
        response = _GraphResponse[_TripData].model_validate_json(body)
        if response.errors or response.data is None:
            raise ValueError("OTP отклонил запрос рейса")
        data = response.data
        version = _version(data.feeds)
        trip = data.trip
        if trip is None or trip.on_service_date is None:
            return TripLookup(version, None)
        calls = trip.on_service_date
        if (
            _local_id(trip.gtfs_id, feed) != occurrence.trip_id
            or calls.service_date != occurrence.service_date
        ):
            raise ValueError("OTP вернул другой экземпляр рейса")
        return TripLookup(
            version,
            TripTimetable(
                occurrence,
                tuple(call.as_call(feed) for call in calls.stop_calls),
                calls.real_time_trip_state is not None and calls.real_time_trip_state.canceled,
            ),
        )
    except ValueError as exc:
        raise TransitPlannerUnavailableError("OTP вернул непригодный ответ рейса") from exc
