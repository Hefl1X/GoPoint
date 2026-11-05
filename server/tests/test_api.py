from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import ManualClock

# Сервер на сохранённых образцах ЦУГАЭТ, часы стоят на моменте снятия образцов.
client = TestClient(
    create_app(Settings(transit_feed="fake"), clock=ManualClock(), start_poller=False)
)


def test_health() -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/v1/health").json() == {"status": "ok"}


def test_meta_has_city_bounds_as_objects() -> None:
    body = client.get("/api/v1/meta").json()
    assert body["appName"] == "GoPoint"
    assert body["lowFloorOnlyDefault"] is True
    sw = body["cityBounds"]["southWest"]
    ne = body["cityBounds"]["northEast"]
    assert set(sw) == {"lat", "lon"}
    assert sw["lat"] < ne["lat"]
    assert sw["lon"] < ne["lon"]


def test_unknown_address_returns_unified_error() -> None:
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.json() == {"code": "NOT_FOUND", "message": "Ничего не нашлось по этому адресу."}


def test_validation_error_does_not_echo_input() -> None:
    response = client.post(
        "/api/v1/route",
        json={"origin": {"lat": 999, "lon": 82.9}, "destination": {"lat": 55.0, "lon": 82.9}},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["message"] == "Проверьте введённые данные."
    assert "999" not in response.text


def test_search_requires_three_characters() -> None:
    assert client.get("/api/v1/search", params={"q": "ле"}).status_code == 422


def test_openapi_lists_contract_endpoints() -> None:
    paths = client.get("/api/openapi.json").json()["paths"]
    for path in [
        "/api/v1/health",
        "/api/v1/meta",
        "/api/v1/search",
        "/api/v1/route",
        "/api/v1/live/vehicles",
        "/api/v1/live/vehicles/{vehicle_id}",
        "/api/v1/live/routes",
        "/api/v1/live/routes/{line_id}",
        "/api/v1/live/stops/{stop_id}/arrivals",
    ]:
        assert path in paths, path


def test_low_floor_only_param_name_in_contract() -> None:
    params = client.get("/api/openapi.json").json()["paths"]["/api/v1/live/vehicles"]["get"][
        "parameters"
    ]
    names = {p["name"]: p for p in params}
    assert names["lowFloorOnly"]["schema"]["default"] is True
