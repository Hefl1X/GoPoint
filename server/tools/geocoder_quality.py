"""Проверка качества поиска адресов (Photon) на 30 местах Новосибирска. Ходит в сеть.

Запуск вручную, не чаще раза в день (около 60 запросов с паузой 1,1 с):
    cd server && uv run python -m tools.geocoder_quality > /tmp/geocoder.md
Свой Photon в Docker снаружи не виден, поэтому для него проверка запускается внутри
контейнера сервера (см. docs/HANDOFF.md). Путь к списку мест можно передать первым аргументом.

Для каждого места два запроса:
- в Photon так, как напечатал бы человек (короткий запрос), тем же путём, что и сайт
  (границы города, отбор повторов, первые 6 подсказок);
- эталон: точный адрес в Nominatim (официальный поиск OpenStreetMap, правила
  https://operations.osmfoundation.org/policies/nominatim/: не чаще 1 запроса в секунду,
  понятный User-Agent). Оба сервиса на данных OpenStreetMap: замер показывает, находит ли
  поиск нужное место по короткому запросу, а не точность самой карты.
«Нашёл» = среди первых трёх подсказок есть точка ближе radius_m к эталону.
"""

from __future__ import annotations

import asyncio
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.adapters.photon.geocoder import PhotonGeocoder
from app.config import get_settings
from app.domain.area import CityArea
from app.domain.geo import distance_m
from app.domain.models import LatLon, PlaceSuggestion
from app.services.geocoding import GeocodingService
from app.wiring import build_local_places

PLACES_CSV = Path(__file__).resolve().parents[2] / "data" / "geocoder" / "places_nsk.csv"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
PAUSE_S = 1.1
TOP = 3


@dataclass
class Row:
    id: str
    category: str
    query: str
    reference: str
    radius_m: float


@dataclass
class Result:
    row: Row
    ref: LatLon | None
    suggestions: list[PlaceSuggestion]
    error: str | None = None

    @property
    def best(self) -> tuple[int, float] | None:
        """Номер (с 1) ближайшей к эталону подсказки среди первых трёх и расстояние."""
        if self.ref is None or not self.suggestions:
            return None
        ref = self.ref
        dists = [distance_m(s.point, ref) for s in self.suggestions[:TOP]]
        i = min(range(len(dists)), key=dists.__getitem__)
        return i + 1, dists[i]


def load_rows() -> list[Row]:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else PLACES_CSV
    with path.open(encoding="utf-8") as f:
        return [
            Row(r["id"], r["category"], r["query"], r["reference"], float(r["radius_m"]))
            for r in csv.DictReader(f)
        ]


async def nominatim(client: httpx.AsyncClient, query: str) -> LatLon | None:
    s = get_settings()
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": "1",
        "countrycodes": "ru",
        "viewbox": f"{s.city_west},{s.city_north},{s.city_east},{s.city_south}",
        "bounded": "1",
    }
    response = await client.get(NOMINATIM, params=params)
    response.raise_for_status()
    body: Any = response.json()
    if not body:
        return None
    return LatLon(lat=float(body[0]["lat"]), lon=float(body[0]["lon"]))


def verdict(r: Result) -> str:
    if r.error:
        return "ошибка"
    best = r.best
    if r.ref is None:
        return "эталон не найден"
    if best is None:
        return "нет"
    pos, dist = best
    return f"да ({pos}-я)" if dist <= r.row.radius_m else "нет"


def fmt_dist(r: Result) -> str:
    best = r.best
    return "—" if best is None else f"{best[1]:.0f}"


async def main() -> None:
    settings = get_settings()
    photon = PhotonGeocoder(base_url=settings.photon_url, user_agent=settings.user_agent)
    service = GeocodingService(
        photon,
        area=CityArea(bounds=settings.city_bounds),
        near=settings.city_center,
        limit=settings.search_limit,
        min_interval_s=PAUSE_S,
    )
    service.set_local(build_local_places(lambda: []))  # синонимы; остановок без сервера нет
    results: list[Result] = []
    async with httpx.AsyncClient(headers={"User-Agent": settings.user_agent}, timeout=15) as client:
        for row in load_rows():
            try:
                suggestions = await service.search(row.query)
                await asyncio.sleep(PAUSE_S)
                ref = await nominatim(client, row.reference)
                await asyncio.sleep(PAUSE_S)
                results.append(Result(row, ref, suggestions))
            except Exception as exc:  # noqa: BLE001  отчёт должен дойти до конца
                results.append(Result(row, None, [], error=type(exc).__name__))
    await photon.aclose()

    print("| № | Что | Запрос | Первая подсказка | Нашёл | Промах, м |")
    print("|---|---|---|---|---|---|")
    for r in results:
        first = r.suggestions[0] if r.suggestions else None
        first_text = (
            "—"
            if first is None
            else first.title + (f" ({first.subtitle})" if first.subtitle else "")
        )
        print(
            f"| {r.row.id} | {r.row.category} | {r.row.query} | {first_text} "
            f"| {verdict(r)} | {fmt_dist(r)} |"
        )
    found = sum(1 for r in results if verdict(r).startswith("да"))
    checked = sum(1 for r in results if r.ref is not None and not r.error)
    print()
    print(f"Нашёл: {found} из {checked} мест с эталоном (всего мест {len(results)}).")


if __name__ == "__main__":
    asyncio.run(main())
