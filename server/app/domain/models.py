"""Модели предметной области GoPoint.

Здесь нет сети, адаптеров и FastAPI: только данные и правила.
Координаты всегда объект LatLon {lat, lon}, не массив.
Имена полей в JSON пишутся в camelCase (lowFloor, arriveAt), в Python в snake_case.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class DomainModel(BaseModel):
    """Общая база: camelCase в JSON, неизменяемые объекты, лишние поля запрещены."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        frozen=True,
        extra="forbid",
    )


class LatLon(DomainModel):
    """Точка на карте. Широта и долгота в градусах WGS 84."""

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Bounds(DomainModel):
    """Прямоугольник на карте: юго-западный и северо-восточный углы."""

    south_west: LatLon
    north_east: LatLon

    def contains(self, point: LatLon) -> bool:
        return (
            self.south_west.lat <= point.lat <= self.north_east.lat
            and self.south_west.lon <= point.lon <= self.north_east.lon
        )


class Accessibility(StrEnum):
    """Низкий пол у машины. unknown никогда не показывается как yes."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class TransportType(StrEnum):
    BUS = "bus"
    TROLLEYBUS = "trolleybus"
    TRAM = "tram"
    MINIBUS = "minibus"


class Place(DomainModel):
    """Точка А или Б: адрес, место или точка, выбранная на карте."""

    name: str | None = None
    point: LatLon


class PlaceKind(StrEnum):
    """Что за место нашёл поиск: от этого зависит значок в подсказке."""

    ADDRESS = "address"  # дом с номером
    STREET = "street"
    STOP = "stop"  # остановка транспорта
    PLACE = "place"  # организация, торговый центр, больница и т. п.
    AREA = "area"  # район, микрорайон, посёлок


class PlaceSuggestion(DomainModel):
    """Подсказка поиска адреса: что показать человеку и где это на карте."""

    id: str
    title: str = Field(min_length=1)
    subtitle: str | None = None
    kind: PlaceKind
    point: LatLon


class Stop(DomainModel):
    id: str
    name: str
    point: LatLon


class Line(DomainModel):
    """Маршрут транспорта (например, автобус 13). Номера повторяются у разных видов."""

    id: str
    type: TransportType
    number: str
    title: str
    ring: bool = Field(default=False, description="Кольцевой маршрут (без конечной)")


class Direction(StrEnum):
    """Направление маршрута: A прямое, B обратное."""

    A = "A"
    B = "B"


class Vehicle(DomainModel):
    """Машина на линии сейчас."""

    id: str
    line_id: str
    type: TransportType
    number: str
    direction: Direction
    point: LatLon
    azimuth: int | None = Field(default=None, ge=0, le=360)
    speed_kmh: float | None = Field(default=None, ge=0)
    low_floor: Accessibility
    position_observed_at: datetime = Field(
        description="Служебное: когда машина отметилась (UTC). Интерфейс не показывает."
    )


class RouteStop(DomainModel):
    """Остановка на линии маршрута в порядке движения."""

    order: int = Field(ge=0)
    stop: Stop
    point_index: int = Field(ge=0, description="Номер точки линии, где стоит остановка")


class LinePath(DomainModel):
    """Линия маршрута в одном направлении: точки по порядку и остановки на ней."""

    line_id: str
    direction: Direction
    points: list[LatLon]
    stops: list[RouteStop]


class VehicleState(StrEnum):
    """Служебное: что делает машина по данным источника."""

    ON_ROUTE = "on_route"
    NO_PLAN = "no_plan"
    PARKED = "parked"
    LUNCH = "lunch"


class PlannedStop(DomainModel):
    """Служебное: время прохода контрольной остановки по плану машины (UTC)."""

    stop_name: str
    at: datetime


class LiveVehicle(DomainModel):
    """Машина вместе со служебными сведениями для расчётов (наружу не отдаётся целиком)."""

    vehicle: Vehicle
    state: VehicleState
    on_line: bool = Field(description="Показал бы её сайт источника (не отстой, не обед)")
    stops_passed: int | None = Field(
        default=None, ge=0, description="Сколько остановок направления уже проехала (±1)"
    )
    plan: list[PlannedStop] = Field(default_factory=list)


class EtaMethod(StrEnum):
    """Служебное: как посчитано время прихода. Интерфейс его не называет."""

    PLANNED = "planned"
    DISTANCE = "distance"


class EtaDiagnostics(DomainModel):
    """Служебные сведения о расчёте: для логов и тестов, не для экрана."""

    method: EtaMethod
    position_observed_at: datetime


class Eta(DomainModel):
    """Когда машина придёт на остановку."""

    stop_id: str
    arrive_at: datetime
    diagnostics: EtaDiagnostics


class StopArrival(DomainModel):
    """Машина подъезжает к остановке (экран остановки)."""

    vehicle: Vehicle
    toward: str | None = Field(
        default=None, description="Конечная, куда едет машина; null у кольцевых"
    )
    stops_away: int = Field(
        ge=0, description="Сколько остановок машине осталось до этой (0: эта следующая)"
    )
    arrive_at: datetime
    diagnostics: EtaDiagnostics


class NextStop(DomainModel):
    """Остановка впереди машины и когда машина на неё придёт (карточка машины)."""

    stop: Stop
    arrive_at: datetime
    diagnostics: EtaDiagnostics


class WalkLeg(DomainModel):
    """Пеший участок по улицам и тротуарам."""

    kind: Literal["walk"] = "walk"
    origin: Place
    destination: Place
    distance_m: int = Field(ge=0)
    duration_s: int = Field(ge=0)
    geometry: list[LatLon] = Field(default_factory=list)
    # Подъём и спуск за участок по данным рельефа, метры (если рельеф известен).
    climb_m: float | None = Field(default=None, ge=0)
    descent_m: float | None = Field(default=None, ge=0)
    # На пути есть лестница или эскалатор (OTP идёт через них, только если иначе никак).
    has_stairs: bool = False


class TransitLeg(DomainModel):
    """Поездка на конкретной машине."""

    kind: Literal["transit"] = "transit"
    vehicle_id: str
    line: Line
    low_floor: Accessibility
    board_stop: Stop
    alight_stop: Stop
    wait_s: int = Field(ge=0, description="Ожидание машины на остановке посадки")
    stops_count: int = Field(ge=1, description="Сколько остановок ехать до выхода")
    stops_away: int = Field(
        ge=0, description="Сколько остановок машине осталось до посадки (0: следующая)"
    )
    toward: str | None = Field(
        default=None, description="Конечная, куда едет машина; null у кольцевых"
    )
    geometry: list[LatLon] = Field(
        default_factory=list, description="Линия маршрута от посадки до выхода"
    )
    depart_at: datetime
    arrive_at: datetime
    diagnostics: EtaDiagnostics


Leg = Annotated[WalkLeg | TransitLeg, Field(discriminator="kind")]


# Чем вариант лучше других (экран показывает до трёх вариантов с такими пометками).
VariantLabel = Literal["fastest", "fewest_transfers", "least_walking"]


class Journey(DomainModel):
    """Один вариант маршрута от А до Б с разбивкой по шагам."""

    legs: list[Leg]
    depart_at: datetime
    arrive_at: datetime
    duration_s: int = Field(ge=0)
    transfers: int = Field(ge=0)
    low_floor_only: bool
    labels: list[VariantLabel] = Field(
        default_factory=list,
        description=(
            "Чем вариант лучше других: fastest — быстрее всего, fewest_transfers — меньше "
            "пересадок, least_walking — меньше пешком; пусто у запасного варианта"
        ),
    )


class ApiError(DomainModel):
    """Единый формат ошибки: код, понятное сообщение по-русски, подробности."""

    code: str
    message: str
    details: dict[str, object] | None = None
