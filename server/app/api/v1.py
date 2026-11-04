"""Адреса /api/v1 (раздел 9 docs/ARCHITECTURE.md).

Пока работают /health и /meta. Остальные адреса уже описаны в контракте
(OpenAPI), чтобы сайт мог строиться на их типах, и отвечают 501 до своих задач.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.errors import ERROR_RESPONSES, not_implemented
from app.api.schemas import (
    ArrivalsResponse,
    Health,
    LineDetails,
    LinesResponse,
    Meta,
    RouteRequest,
    RouteResponse,
    SearchResponse,
    VehicleDetails,
    VehiclesResponse,
)
from app.config import APP_NAME, APP_VERSION, Settings, get_settings
from app.domain.models import TransportType

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


@router.get("/health", tags=["service"])
async def health() -> Health:
    return Health()


@router.get("/meta", tags=["service"])
async def meta(settings: Annotated[Settings, Depends(get_settings)]) -> Meta:
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
    low_floor_only: LowFloorOnly = True,
    bbox: Annotated[
        str | None,
        Query(description="Видимая область: south,west,north,east"),
    ] = None,
) -> VehiclesResponse:
    raise not_implemented()


@router.get("/live/vehicles/{vehicle_id}", tags=["live"])
async def live_vehicle(vehicle_id: str) -> VehicleDetails:
    raise not_implemented()


@router.get("/live/routes", tags=["live"])
async def live_routes(
    low_floor_only: LowFloorOnly = True,
    type: TransportType | None = None,  # noqa: A002 (имя параметра из контракта)
) -> LinesResponse:
    raise not_implemented()


@router.get("/live/routes/{line_id}", tags=["live"])
async def live_route(line_id: str, low_floor_only: LowFloorOnly = True) -> LineDetails:
    raise not_implemented()


@router.get("/live/stops/{stop_id}/arrivals", tags=["live"])
async def live_stop_arrivals(stop_id: str, low_floor_only: LowFloorOnly = True) -> ArrivalsResponse:
    raise not_implemented()
