"""Адреса /api/v1 (раздел 9 docs/ARCHITECTURE.md).

Работают: /health, /meta, /live/vehicles, /live/routes, /live/routes/{id}.
Остальные уже описаны в контракте (OpenAPI) и отвечают 501 до своих задач.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.errors import ERROR_RESPONSES, AppError, not_implemented
from app.api.schemas import (
    ArrivalsResponse,
    Health,
    LineDetails,
    LineDirection,
    LinesResponse,
    LineSummary,
    Meta,
    RouteRequest,
    RouteResponse,
    SearchResponse,
    SnapshotDiagnostics,
    VehicleDetails,
    VehiclesResponse,
)
from app.config import APP_NAME, APP_VERSION, Settings
from app.domain.live import line_sort_key, usable_vehicles
from app.domain.models import Bounds, Direction, LatLon, TransportType
from app.ports import TransitFeedError, UnknownLineError
from app.services.live_snapshot import Clock, LiveSnapshotService, Snapshot

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


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
LiveDep = Annotated[LiveSnapshotService, Depends(get_live)]
ClockDep = Annotated[Clock, Depends(get_clock)]


def transit_unavailable() -> AppError:
    return AppError(
        503,
        "TRANSIT_UNAVAILABLE",
        "Не удалось получить данные о транспорте. Попробуйте через минуту.",
    )


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
async def search(q: Annotated[str, Query(min_length=3, max_length=200)]) -> SearchResponse:
    raise not_implemented()


@router.post("/route", tags=["route"])
async def route(body: RouteRequest) -> RouteResponse:
    raise not_implemented()


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
async def live_vehicle(vehicle_id: str) -> VehicleDetails:
    raise not_implemented()


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
                    vehicles=[v for v in vehicles if v.direction is direction],
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
async def live_stop_arrivals(stop_id: str, low_floor_only: LowFloorOnly = True) -> ArrivalsResponse:
    raise not_implemented()
