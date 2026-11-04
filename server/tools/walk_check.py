"""Проверка 10 пеших маршрутов по Новосибирску на своём OTP (ходит в сервисы Docker).

Запуск внутри контейнера сервера (OTP и Photon снаружи не видны):
    C=$(docker compose ps -q server); docker cp server/tools $C:/tmp/tools
    docker compose exec -w /tmp server sh -c \
      'PYTHONPATH=/app:/tmp /app/.venv/bin/python -m tools.walk_check /tmp/walk'
    docker cp $C:/tmp/walk/. data/walk/

Точки заданы координатами (взяты из поиска адресов), маршрут строится дважды:
по профилю коляски (как в приложении) и обычным пешеходом (для сравнения: если
путь для коляски длиннее, значит OTP обходит лестницы, бордюры или крутые места).
Пишет walk_check.md (таблица) и walk_check.html (карта).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx

from app.adapters.otp.parse import parse_walk
from app.adapters.otp.walk import GRAPHQL_PATH, QUERY
from app.config import get_settings
from app.domain.models import LatLon, Place, WalkLeg

# Точки взяты из нашего поиска адресов (Photon, OpenStreetMap) 04.11.2026.
Point = tuple[str, float, float]
PAIRS: list[tuple[str, Point, Point]] = [
    (
        "Спуск к Оби",
        ("Метро «Речной вокзал»", 55.00895, 82.93838),
        ("Михайловская набережная", 55.00601, 82.93707),
    ),
    (
        "Вокзал → центр",
        ("Вокзал Новосибирск-Главный", 55.03576, 82.89618),
        ("Красный проспект, 17", 55.02653, 82.92079),
    ),
    (
        "Через лог реки Каменки",
        ("Каменская улица, 32", 55.03003, 82.92899),
        ("Метро «Октябрьская»", 55.01896, 82.93914),
    ),
    (
        "Метро → университет",
        ("Метро «Студенческая»", 54.98931, 82.90664),
        ("НГТУ, корпус 1", 54.98778, 82.90647),
    ),
    (
        "Два торговых центра",
        ("ТЦ «Аура»", 55.02867, 82.93657),
        ("ТЦ «Галерея Новосибирск»", 55.0435, 82.92228),
    ),
    ("Академгородок", ("Морской проспект, 2", 54.84093, 83.11023), ("НГУ", 54.84613, 83.09422)),
    (
        "Парк → театр",
        ("Центральный парк", 55.03524, 82.92617),
        ("Оперный театр", 55.03042, 82.92452),
    ),
    (
        "Заельцовский парк",
        ("Метро «Заельцовская»", 55.05945, 82.91251),
        ("Касса зоопарка, Тимирязева 71/5а", 55.05374, 82.88),
    ),
    (
        "Площадь Маркса → Мега",
        ("Метро «Площадь Маркса»", 54.98305, 82.89303),
        ("ТЦ «Мега»", 54.96428, 82.93623),
    ),
    (
        "Больница: корпус → корпус",
        ("ГНоКБ, Немировича-Данченко 130", 54.98328, 82.91429),
        ("Перинатальный центр", 54.98474, 82.91604),
    ),
]

ERROR_TEXT = {
    "NoAccessibleWalkError": "путь только по лестнице или эскалатору",
    "NoWalkRouteError": "пути по улицам нет",
    "PointNotOnStreetError": "точка не у улицы",
}

COLORS = [
    "#0f6b5c",
    "#1d4ed8",
    "#b4236b",
    "#8a3a0f",
    "#6d28d9",
    "#c2410c",
    "#047857",
    "#4338ca",
    "#be123c",
    "#0369a1",
]


async def walk(client: httpx.AsyncClient, a: Place, b: Place, wheelchair: bool) -> WalkLeg:
    query = QUERY if wheelchair else QUERY.replace("enabled: true", "enabled: false")

    def loc(p: Place) -> dict[str, Any]:
        return {"location": {"coordinate": {"latitude": p.point.lat, "longitude": p.point.lon}}}

    variables = {"from": loc(a), "to": loc(b), "speed": get_settings().walk_speed_mps}
    response = await client.post(GRAPHQL_PATH, json={"query": query, "variables": variables})
    response.raise_for_status()
    return parse_walk(response.json(), a, b)


def minutes(seconds: int) -> str:
    return f"{seconds / 60:.0f}"


async def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "walk_out")
    out.mkdir(parents=True, exist_ok=True)
    s = get_settings()
    rows: list[str] = []
    features: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=s.otp_url, timeout=30) as client:
        for i, (title, (name_a, lat_a, lon_a), (name_b, lat_b, lon_b)) in enumerate(PAIRS, 1):
            a = Place(name=name_a, point=LatLon(lat=lat_a, lon=lon_a))
            b = Place(name=name_b, point=LatLon(lat=lat_b, lon=lon_b))
            try:
                chair = await walk(client, a, b, wheelchair=True)
                plain = await walk(client, a, b, wheelchair=False)
            except Exception as exc:  # noqa: BLE001  отчёт должен дойти до конца
                error = ERROR_TEXT.get(type(exc).__name__, type(exc).__name__)
                rows.append(f"| {i} | {title} | {name_a} → {name_b} | ошибка: {error} | | | | | |")
                continue
            speed = chair.distance_m / chair.duration_s if chair.duration_s else 0
            detour = chair.distance_m - plain.distance_m
            rows.append(
                f"| {i} | {title} | {name_a} → {name_b} | {chair.distance_m} | "
                f"{minutes(chair.duration_s)} | {speed:.2f} | "
                f"{chair.climb_m if chair.climb_m is not None else '—'} / "
                f"{chair.descent_m if chair.descent_m is not None else '—'} | "
                f"{plain.distance_m} ({'+' if detour >= 0 else ''}{detour}) | "
                f"{'да' if chair.has_stairs else 'нет'} / {'да' if plain.has_stairs else 'нет'} |"
            )
            color = COLORS[(i - 1) % len(COLORS)]
            for leg, kind in ((chair, "коляска"), (plain, "пешеход")):
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "n": i,
                            "title": title,
                            "kind": kind,
                            "color": color,
                            "text": (
                                f"{i}. {title}: {leg.distance_m} м, "
                                f"{minutes(leg.duration_s)} мин ({kind})"
                            ),
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[p.lon, p.lat] for p in leg.geometry],
                        },
                    }
                )

    table = [
        "| № | Что проверяем | Откуда → куда | Метров (коляска) | Минут "
        "| Средняя скорость, м/с | Подъём / спуск, м | Обычный пешеход, м (разница) "
        "| Лестница: коляска / пешеход |",
        "|---|---|---|---|---|---|---|---|---|",
        *rows,
    ]
    (out / "walk_check.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    geojson = json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False)
    template = (Path(__file__).parent / "walk_check_template.html").read_text(encoding="utf-8")
    (out / "walk_check.html").write_text(template.replace("__DATA__", geojson), encoding="utf-8")
    print("\n".join(table))


if __name__ == "__main__":
    asyncio.run(main())
