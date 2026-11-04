"""Адаптер Photon без сети: подменённый транспорт httpx."""

import json
from pathlib import Path

import httpx
import pytest

from app.adapters.photon.geocoder import PhotonGeocoder
from app.domain.models import Bounds, LatLon
from app.ports import GeocoderError

SAMPLES = Path(__file__).parent / "photon_samples"
BOUNDS = Bounds(south_west=LatLon(lat=54.8, lon=82.7), north_east=LatLon(lat=55.2, lon=83.2))
CENTER = LatLon(lat=55.03, lon=82.92)


def geocoder(handler: httpx.MockTransport) -> PhotonGeocoder:
    return PhotonGeocoder(
        base_url="https://photon.test", user_agent="GoPoint/test", transport=handler
    )


async def test_search_sends_documented_params() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads((SAMPLES / "search_aura.json").read_text(encoding="utf-8"))
        return httpx.Response(200, json=body)

    g = geocoder(httpx.MockTransport(handle))
    items = await g.search("аура", limit=6, bounds=BOUNDS, near=CENTER)
    await g.aclose()

    assert [i.title for i in items] == ["Аура"]
    params = seen[0].url.params
    assert seen[0].url.path == "/api/"
    assert params["q"] == "аура"
    assert params["bbox"] == "82.7,54.8,83.2,55.2"  # minLon,minLat,maxLon,maxLat
    assert params["lang"] == "default"
    assert (params["lat"], params["lon"]) == ("55.03", "82.92")
    assert seen[0].headers["User-Agent"] == "GoPoint/test"


async def test_reverse_returns_first_or_none() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/reverse"
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    g = geocoder(httpx.MockTransport(handle))
    assert await g.reverse(CENTER) is None
    await g.aclose()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="oops"),
        httpx.Response(429, text="slow down"),
        httpx.Response(200, text="<html>"),
        httpx.Response(200, json={"error": "x"}),
    ],
)
async def test_bad_answers_become_geocoder_error(response: httpx.Response) -> None:
    g = geocoder(httpx.MockTransport(lambda _r: response))
    with pytest.raises(GeocoderError):
        await g.search("аура", limit=6, bounds=BOUNDS, near=CENTER)
    await g.aclose()


async def test_no_connection_becomes_geocoder_error() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    g = geocoder(httpx.MockTransport(handle))
    with pytest.raises(GeocoderError):
        await g.reverse(CENTER)
    await g.aclose()
