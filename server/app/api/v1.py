"""Адреса /api/v1 (раздел 9 docs/ARCHITECTURE.md).

Работают все адреса: /health, /meta, /search, /search/reverse, /walk, /route,
/route/check, /live/vehicles, /live/vehicles/{id}, /live/routes, /live/routes/{id},
/live/stops/{id}/arrivals.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.errors import ERROR_RESPONSES, AppError
from app.api.schemas import (
    ArrivalsResponse,
    Health,
    LineDetails,
    LineDirection,
    LinesResponse,
    LineSummary,
    LineVehicle,
    Meta,
    ReverseResponse,
    RouteCheckRequest,
    RouteCheckResponse,
    RouteRequest,
    RouteResponse,
    SearchResponse,
    SnapshotDiagnostics,
    VehicleDetails,
    VehiclesResponse,
    WalkRequest,
)
from app.config import APP_NAME, APP_VERSION, Settings
from app.domain.area import CityArea
from app.domain.geo import next_stop_order
from app.domain.live import line_sort_key, usable_vehicles
from app.domain.models import Bounds, Direction, LatLon, Place, TransportType, WalkLeg
from app.ports import (
    GeocoderError,
    NoAccessibleWalkError,
    NoWalkRouteError,
    PointNotOnStreetError,
    TransitFeedError,
    UnknownLineError,
    WalkPlannerError,
)
from app.services.geocoding import GeocodingService
from app.services.journey_planner import JourneyPlanner, TransitUnavailableError
from app.services.live_snapshot import Clock, LiveSnapshotService, Snapshot
from app.services.walking import WalkingService

router = APIRouter(prefix="/api/v1", responses=ERROR_RESPONSES)

LowFloorOnly = Annotated[
    bool,
    Query(
        alias="lowFloorOnly",
        description=(
            "true: только машины с низким полом (yes); false: все машины на линии с пометкой"
        ),
    ),
]


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_live(request: Request) -> LiveSnapshotService:
    live: LiveSnapshotService = request.app.state.live
    return live


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


def get_geocoding(request: Request) -> GeocodingService:
    geocoding: GeocodingService = request.app.state.geocoding
    return geocoding


def get_walking(request: Request) -> WalkingService:
    walking: WalkingService = request.app.state.walking
    return walking


def get_planner(request: Request) -> JourneyPlanner:
    planner: JourneyPlanner = request.app.state.planner
    return planner


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
LiveDep = Annotated[LiveSnapshotService, Depends(get_live)]
ClockDep = Annotated[Clock, Depends(get_clock)]
GeocodingDep = Annotated[GeocodingService, Depends(get_geocoding)]
WalkingDep = Annotated[WalkingService, Depends(get_walking)]
PlannerDep = Annotated[JourneyPlanner, Depends(get_planner)]

NO_TRANSIT_MESSAGE = "Транспорта сейчас нет"


def transit_unavailable() -> AppError:
    return AppError(
        503,
        "TRANSIT_UNAVAILABLE",
        "Не удалось получить данные о транспорте. Попробуйте через минуту.",
    )


def geocoder_unavailable() -> AppError:
    return AppError(
        503,
        "GEOCODER_UNAVAILABLE",
        "Поиск адресов сейчас не работает. Выберите точку на карте.",
    )


def outside_city() -> AppError:
    return AppError(422, "OUTSIDE_CITY", "Эта точка за пределами Новосибирска.")


def line_not_found() -> AppError:
    return AppError(404, "LINE_NOT_FOUND", "Такого маршрута нет.")


async def _snapshot(live: LiveSnapshotService) -> Snapshot:
    try:
        return await live.snapshot()
    except TransitFeedError as exc:
        raise transit_unavailable() from exc


def _diagnostics(snap: Snapshot) -> SnapshotDiagnostics:
    return SnapshotDiagnostics(fetched_at=snap.fetched_at, complete=snap.complete)


def parse_bbox(value: str) -> Bounds:
    bad = AppError(
        422,
        "BAD_BBOX",
        "Проверьте введённые данные.",
        {"field": "bbox", "expected": "south,west,north,east"},
    )
    parts = value.split(",")
    if len(parts) != 4:
        raise bad
    try:
        south, west, north, east = (float(p) for p in parts)
        bounds = Bounds(
            south_west=LatLon(lat=south, lon=west), north_east=LatLon(lat=north, lon=east)
        )
    except ValueError as exc:
        raise bad from exc
    if south > north or west > east:
        raise bad
    return bounds


@router.get("/health", tags=["service"])
async def health() -> Health:
    return Health()


@router.get("/meta", tags=["service"])
async def meta(settings: SettingsDep) -> Meta:
    return Meta(
        app_name=APP_NAME,
        version=APP_VERSION,
        city_bounds=settings.city_bounds,
        refresh_interval_s=settings.refresh_interval_s,
        stale_seconds=settings.stale_seconds,
    )


@router.get("/search", tags=["search"])
async def search(
    geocoding: GeocodingDep,
    q: Annotated[str, Query(min_length=3, max_length=200, description="Адрес или название")],
) -> SearchResponse:
    """Подсказки адресов и мест в Новосибирске (данные OpenStreetMap)."""
    try:
        places = await geocoding.search(q)
    except GeocoderError as exc:
        raise geocoder_unavailable() from exc
    return SearchResponse(places=places)


@router.get("/search/reverse", tags=["search"])
async def search_reverse(
    geocoding: GeocodingDep,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
) -> ReverseResponse:
    """Адрес у точки, выбранной на карте."""
    point = LatLon(lat=lat, lon=lon)
    if not geocoding.area.contains(point):
        raise outside_city()
    try:
        place = await geocoding.reverse(point)
    except GeocoderError as exc:
        raise geocoder_unavailable() from exc
    return ReverseResponse(place=place)


def walk_error(exc: WalkPlannerError) -> AppError:
    if isinstance(exc, PointNotOnStreetError):
        return AppError(
            422,
            "POINT_NOT_ON_STREET",
            "Рядом с точкой не нашлось улицы или тротуара. Выберите точку ближе к дороге.",
        )
    if isinstance(exc, NoAccessibleWalkError):
        return AppError(
            422,
            "NO_ACCESSIBLE_WALK",
            "Отсюда нашёлся путь только по лестнице или эскалатору. Выберите точку ближе к улице.",
        )
    if isinstance(exc, NoWalkRouteError):
        return AppError(422, "NO_WALK_ROUTE", "Не нашли путь по улицам между этими точками.")
    return AppError(
        503,
        "WALK_UNAVAILABLE",
        "Не удалось посчитать путь по улицам. Попробуйте через минуту.",
    )


@router.post("/walk", tags=["route"])
async def walk(body: WalkRequest, city: CityDep, walking: WalkingDep) -> WalkLeg:
    """Пеший участок по профилю коляски: время, расстояние, линия. Служебный адрес для
    проверки и для расчёта маршрута; профиль коляски включён всегда."""
    _check_points(city, body.origin, body.destination)
    try:
        return await walking.walk(Place(point=body.origin), Place(point=body.destination))
    except WalkPlannerError as exc:
        raise walk_error(exc) from exc


def get_city(request: Request) -> CityArea:
    city: CityArea = request.app.state.city
    return city


CityDep = Annotated[CityArea, Depends(get_city)]


def _check_points(city: CityArea, *points: LatLon) -> None:
    if not all(city.contains(p) for p in points):
        raise outside_city()


@router.post("/route", tags=["route"])
async def route(body: RouteRequest, city: CityDep, planner: PlannerDep) -> RouteResponse:
    """Маршрут «сейчас» по машинам на линии: до 3 вариантов с шагами и временем.

    lowFloorOnly = true: только машины с низким полом (yes); false: любые, у каждой
    поездки пометка lowFloor. Пешие участки всегда по профилю коляски.
    """
    _check_points(city, body.origin, body.destination)
    try:
        outcome = await planner.plan(
            body.origin, body.destination, low_floor_only=body.low_floor_only
        )
    except TransitUnavailableError as exc:
        raise transit_unavailable() from exc
    except WalkPlannerError as exc:
        raise walk_error(exc) from exc
    return RouteResponse(
        journeys=outcome.journeys,
        status=outcome.status,
        message=NO_TRANSIT_MESSAGE if outcome.status == "no_transit" else None,
        walk=outcome.walk,
        diagnostics=_diagnostics(outcome.snapshot),
    )


@router.post("/route/check", tags=["route"])
async def route_check(
    body: RouteCheckRequest, city: CityDep, settings: SettingsDep, planner: PlannerDep
) -> RouteCheckResponse:
    """Пересчёт выбранного маршрута: машина стоит, пропала или опаздывает — есть ли вариант
    лучше. Маршрут не заменяется: решает человек."""
    _check_points(city, body.origin, body.destination)
    try:
        outcome = await planner.check(
            body.origin,
            body.destination,
            low_floor_only=body.low_floor_only,
            vehicle_id=body.vehicle_id,
            planned_arrive_at=body.planned_arrive_at,
            stopped_threshold=timedelta(seconds=settings.stopped_threshold_s),
            late_threshold=timedelta(seconds=settings.late_threshold_s),
        )
    except TransitUnavailableError as exc:
        raise transit_unavailable() from exc
    except WalkPlannerError as exc:
        raise walk_error(exc) from exc
    return RouteCheckResponse(
        status=outcome.status,
        stopped_for_s=outcome.stopped_for_s,
        current=outcome.current,
        alternative=outcome.alternative,
        gain_s=outcome.gain_s,
        diagnostics=_diagnostics(outcome.snapshot),
    )


@router.get("/live/vehicles", tags=["live"])
async def live_vehicles(
    live: LiveDep,
    settings: SettingsDep,
    clock: ClockDep,
    low_floor_only: LowFloorOnly = True,
    bbox: Annotated[
        str | None,
        Query(description="Видимая область: south,west,north,east"),
    ] = None,
) -> VehiclesResponse:
    bounds = parse_bbox(bbox) if bbox is not None else None
    snap = await _snapshot(live)
    vehicles = usable_vehicles(
        snap.vehicles, clock(), settings.stale_seconds, low_floor_only, bounds
    )
    return VehiclesResponse(vehicles=vehicles, diagnostics=_diagnostics(snap))


@router.get("/live/vehicles/{vehicle_id}", tags=["live"])
async def live_vehicle(vehicle_id: str, planner: PlannerDep) -> VehicleDetails:
    """Машина на линии и когда она придёт на остановки впереди (карточка машины)."""
    try:
        outcome = await planner.vehicle_details(vehicle_id)
    except TransitUnavailableError as exc:
        raise transit_unavailable() from exc
    if outcome.vehicle is None:
        raise AppError(404, "VEHICLE_NOT_FOUND", "Этой машины сейчас нет на линии.")
    return VehicleDetails(
        vehicle=outcome.vehicle,
        toward=outcome.toward,
        next_stops=outcome.next_stops,
        diagnostics=_diagnostics(outcome.snapshot),
    )


@router.get("/live/routes", tags=["live"])
async def live_routes(
    live: LiveDep,
    settings: SettingsDep,
    clock: ClockDep,
    low_floor_only: LowFloorOnly = True,
    type: TransportType | None = None,  # noqa: A002 (имя параметра из контракта)
) -> LinesResponse:
    snap = await _snapshot(live)
    try:
        lines = await live.lines()
    except TransitFeedError as exc:
        raise transit_unavailable() from exc
    now: datetime = clock()
    summaries = [
        LineSummary(
            line=line,
            vehicles_on_line=len(
                usable_vehicles(
                    snap.by_line.get(line.id, []), now, settings.stale_seconds, low_floor_only
                )
            ),
        )
        for line in sorted(lines, key=line_sort_key)
        if type is None or line.type is type
    ]
    return LinesResponse(lines=summaries, diagnostics=_diagnostics(snap))


@router.get("/live/routes/{line_id}", tags=["live"])
async def live_route(
    line_id: str,
    live: LiveDep,
    settings: SettingsDep,
    clock: ClockDep,
    low_floor_only: LowFloorOnly = True,
) -> LineDetails:
    try:
        line = await live.line(line_id)
        if line is None:
            raise line_not_found()
        snap = await _snapshot(live)
        vehicles = usable_vehicles(
            snap.by_line.get(line_id, []), clock(), settings.stale_seconds, low_floor_only
        )
        directions = []
        for direction in Direction:
            try:
                path = await live.line_path(line_id, direction)
            except TransitFeedError:
                # У кольцевых маршрутов второго направления может не быть.
                continue
            directions.append(
                LineDirection(
                    direction=direction,
                    stops=[s.stop for s in path.stops],
                    path=path.points,
                    vehicles=[
                        LineVehicle(vehicle=v, next_stop_order=next_stop_order(path, v.point))
                        for v in vehicles
                        if v.direction is direction
                    ],
                )
            )
    except UnknownLineError as exc:
        raise line_not_found() from exc
    except TransitFeedError as exc:
        raise transit_unavailable() from exc
    if not directions:
        raise transit_unavailable()
    return LineDetails(line=line, directions=directions, diagnostics=_diagnostics(snap))


@router.get("/live/stops/{stop_id}/arrivals", tags=["live"])
async def live_stop_arrivals(
    stop_id: str, planner: PlannerDep, low_floor_only: LowFloorOnly = True
) -> ArrivalsResponse:
    """Что подъезжает к остановке: машины на линии с временем прихода.

    lowFloorOnly = true: только машины с низким полом (yes); false: любые с пометкой.
    """
    try:
        outcome = await planner.stop_arrivals(stop_id, low_floor_only=low_floor_only)
    except TransitUnavailableError as exc:
        raise transit_unavailable() from exc
    if outcome.stop is None:
        raise AppError(404, "STOP_NOT_FOUND", "Такой остановки нет.")
    return ArrivalsResponse(
        stop=outcome.stop,
        arrivals=outcome.arrivals,
        diagnostics=_diagnostics(outcome.snapshot),
    )
