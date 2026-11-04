import pytest

from app.domain.geo import distance_m, nearest_point_index, next_stop_order
from app.domain.models import Direction, LatLon, LinePath, RouteStop, Stop


def test_distance_one_degree_latitude() -> None:
    assert distance_m(LatLon(lat=55, lon=83), LatLon(lat=56, lon=83)) == pytest.approx(
        111_195, rel=0.001
    )


def test_distance_zero() -> None:
    p = LatLon(lat=55.03, lon=82.92)
    assert distance_m(p, p) == 0


def path() -> LinePath:
    # Линия с запада на восток вдоль широты 55.0: точки через 0.01° долготы (~640 м).
    points = [LatLon(lat=55.0, lon=82.90 + 0.01 * i) for i in range(6)]

    def stop(order: int, index: int) -> RouteStop:
        return RouteStop(
            order=order,
            stop=Stop(id=str(order), name=f"Остановка {order}", point=points[index]),
            point_index=index,
        )

    return LinePath(
        line_id="bus-1",
        direction=Direction.A,
        points=points,
        stops=[stop(0, 0), stop(1, 2), stop(2, 5)],
    )


def test_nearest_point_index() -> None:
    index, dist = nearest_point_index(path().points, LatLon(lat=55.001, lon=82.931))
    assert index == 3
    assert dist == pytest.approx(130, abs=10)


def test_next_stop_between_stops() -> None:
    assert next_stop_order(path(), LatLon(lat=55.0, lon=82.93)) == 2


def test_next_stop_at_first_stop_is_second() -> None:
    assert next_stop_order(path(), LatLon(lat=55.0, lon=82.90)) == 1


def test_next_stop_just_before_stop() -> None:
    assert next_stop_order(path(), LatLon(lat=55.0, lon=82.911)) == 1


def test_at_last_stop_there_is_no_next() -> None:
    assert next_stop_order(path(), LatLon(lat=55.0, lon=82.95)) is None


def test_empty_path() -> None:
    with pytest.raises(ValueError, match="пустая"):
        nearest_point_index([], LatLon(lat=55, lon=83))
