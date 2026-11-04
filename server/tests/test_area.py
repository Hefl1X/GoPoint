"""Граница города: точка внутри многоугольника (без сети)."""

import pytest

from app.adapters.osm_boundary.load import load_polygons, parse_polygons
from app.domain.area import CityArea, Polygon
from app.domain.models import Bounds, LatLon

RECT = Bounds(south_west=LatLon(lat=54.8, lon=82.7), north_east=LatLon(lat=55.2, lon=83.2))


def test_square_with_hole() -> None:
    sq = [
        LatLon(lat=0, lon=0),
        LatLon(lat=0, lon=10),
        LatLon(lat=10, lon=10),
        LatLon(lat=10, lon=0),
    ]
    hole = [LatLon(lat=4, lon=4), LatLon(lat=4, lon=6), LatLon(lat=6, lon=6), LatLon(lat=6, lon=4)]
    poly = Polygon(outer=sq, holes=[hole])
    assert poly.contains(LatLon(lat=2, lon=2))
    assert not poly.contains(LatLon(lat=5, lon=5))
    assert not poly.contains(LatLon(lat=11, lon=5))


@pytest.fixture(scope="module")
def city() -> CityArea:
    return CityArea(bounds=RECT, polygons=load_polygons())


@pytest.mark.parametrize(
    ("name", "lat", "lon", "inside"),
    [
        ("площадь Ленина", 55.0302, 82.9204, True),
        ("Академгородок, НГУ", 54.8461, 83.0942, True),
        ("Заельцовский парк", 55.0590, 82.8890, True),
        ("аэропорт Толмачёво (город Обь)", 55.0126, 82.6507, False),
        ("город Обь, центр", 54.9947, 82.6960, False),
        ("Бердск", 54.7580, 83.1070, False),
        ("Кольцово", 54.9380, 83.1840, False),
    ],
)
def test_novosibirsk_boundary(
    city: CityArea, name: str, lat: float, lon: float, inside: bool
) -> None:
    assert city.contains(LatLon(lat=lat, lon=lon)) is inside, name


def test_without_polygons_rectangle_is_used() -> None:
    area = CityArea(bounds=RECT)
    assert area.contains(LatLon(lat=55.0, lon=82.9))
    assert not area.contains(LatLon(lat=56.0, lon=82.9))


def test_empty_boundary_file_is_an_error() -> None:
    with pytest.raises(ValueError, match="многоугольник"):
        parse_polygons({"features": []})
