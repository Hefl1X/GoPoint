"""Прежние обработчики для сравнения поведения старого поиска на сохранённых данных."""

from datetime import datetime, timedelta

from fastapi import FastAPI
from pydantic import Field

from app.api.errors import install_error_handlers
from app.api.schemas import RouteRequest
from app.api.v1 import STATUS_MESSAGE, outside_city, transit_unavailable, walk_error
from app.config import Settings
from app.domain.area import CityArea
from app.domain.journey_search import SearchParams
from app.domain.models import LatLon
from app.ports import WalkPlannerError
from app.services.journey_planner import JourneyPlanner, PlannerSettings
from app.services.live_snapshot import Clock
from app.services.live_transport import TransitUnavailableError


class _LegacyRequest(RouteRequest):
    low_floor_only: bool = False


class _LegacyCheck(_LegacyRequest):
    vehicle_id: str = Field(min_length=1)
    planned_arrive_at: datetime


def with_legacy_routes(app: FastAPI, settings: Settings, clock: Clock) -> FastAPI:
    fixture = FastAPI()
    fixture.state = app.state
    install_error_handlers(fixture)
    planner = JourneyPlanner(
        app.state.live_transport,
        app.state.walking,
        clock=clock,
        settings=PlannerSettings(
            search=SearchParams(
                board_margin_s=settings.board_margin_s,
                transfer_margin_s=settings.transfer_margin_s,
                board_within_s=settings.horizon_min * 60,
            ),
            transfer_radius_m=settings.transfer_radius_m,
            access_stops=settings.access_stops,
            horizon=timedelta(minutes=settings.horizon_min),
            walk_speed_mps=settings.walk_speed_mps,
            walk_option_max_m=settings.walk_option_max_m,
            access_radius_m=settings.access_radius_m,
            access_stops_max=settings.access_stops_max,
        ),
    )
    city: CityArea = app.state.city

    def inside(origin: LatLon, destination: LatLon) -> None:
        if not city.contains(origin) or not city.contains(destination):
            raise outside_city()

    @fixture.post("/api/v1/route")
    async def route(body: _LegacyRequest) -> dict[str, object]:
        inside(body.origin, body.destination)
        try:
            outcome = await planner.plan(
                body.origin, body.destination, low_floor_only=body.low_floor_only
            )
        except TransitUnavailableError as exc:
            raise transit_unavailable() from exc
        except WalkPlannerError as exc:
            raise walk_error(exc) from exc
        return {
            "journeys": [item.model_dump(by_alias=True) for item in outcome.journeys],
            "status": outcome.status,
            "message": STATUS_MESSAGE.get(outcome.status),
            "walk": outcome.walk.model_dump(by_alias=True) if outcome.walk else None,
        }

    @fixture.post("/api/v1/route/check")
    async def check(body: _LegacyCheck) -> dict[str, object]:
        inside(body.origin, body.destination)
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
        return {
            "status": outcome.status,
            "current": outcome.current.model_dump(by_alias=True) if outcome.current else None,
            "alternative": outcome.alternative.model_dump(by_alias=True)
            if outcome.alternative
            else None,
            "gainS": outcome.gain_s,
            "stoppedForS": outcome.stopped_for_s,
        }

    fixture.mount("/", app)
    return fixture
