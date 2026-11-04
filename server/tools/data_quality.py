"""Замер качества данных ЦУГАЭТ для docs/DATA_QUALITY.md. Ходит в настоящую сеть.

Запуск вручную (не чаще раза в день, делает около 180 запросов с паузой 1 с):
    cd server && uv run python -m tools.data_quality

Печатает сводку в формате Markdown.
"""

from __future__ import annotations

import asyncio
import math
import statistics
from collections import Counter
from datetime import UTC, datetime

from app.adapters.tsugaet.feed import MARKERS_MAX_ROUTES, TsugaetFeed
from app.config import get_settings
from app.domain.models import Direction, LatLon, LinePath, LiveVehicle, TransportType
from app.ports import TransitFeedError, UnknownLineError

PAUSE_S = 1.0  # бережнее, чем при обычном опросе
SEGMENT_SAMPLE = 10


def metres(a: LatLon, b: LatLon) -> float:
    """Расстояние в метрах (равнопромежуточная проекция, для города хватает)."""
    k = math.cos(math.radians((a.lat + b.lat) / 2))
    dx = math.radians(b.lon - a.lon) * k
    dy = math.radians(b.lat - a.lat)
    return 6_371_000 * math.hypot(dx, dy)


def nearest_index(path: LinePath, point: LatLon) -> tuple[int, float]:
    best = min(range(len(path.points)), key=lambda i: metres(path.points[i], point))
    return best, metres(path.points[best], point)


async def poll_all(feed: TsugaetFeed, ids: list[str]) -> list[LiveVehicle]:
    result: list[LiveVehicle] = []
    for i in range(0, len(ids), MARKERS_MAX_ROUTES):
        result.extend(await feed.vehicles(ids[i : i + MARKERS_MAX_ROUTES]))
    return result


async def main() -> None:  # noqa: PLR0915 (одноразовый отчёт, читается сверху вниз)
    settings = get_settings()
    all_types = frozenset(TransportType)
    feed = TsugaetFeed(user_agent=settings.user_agent, pause_s=PAUSE_S, types=all_types)
    try:
        lines = await feed.lines()
        ids = [line.id for line in lines]
        started = datetime.now(UTC)
        first = await poll_all(feed, ids)
        await asyncio.sleep(30)
        second = await poll_all(feed, ids)

        print(f"## Замер {started.astimezone().strftime('%Y-%m-%d %H:%M')} (время Mac)\n")
        types = Counter(line.type.value for line in lines)
        print(f"- Маршрутов: {len(lines)} ({dict(types)})")
        print(
            f"- Машин в ответах всего: {len(first)}, из них на линии: "
            f"{sum(v.on_line for v in first)}"
        )
        states = Counter(v.state.value for v in first)
        print(f"- Состояния машин: {dict(states)}")
        on_line = [v for v in first if v.on_line]
        ramps = Counter(v.vehicle.low_floor.value for v in on_line)
        total = len(on_line) or 1
        print(
            "- Низкий пол у машин на линии: "
            + ", ".join(f"{k} {n} ({100 * n / total:.0f}%)" for k, n in ramps.most_common())
        )
        by_type = Counter((v.vehicle.type.value, v.vehicle.low_floor.value) for v in on_line)
        print(f"- По видам (вид, признак): {dict(sorted(by_type.items()))}")

        ages = [(started - v.vehicle.position_observed_at).total_seconds() for v in on_line]
        if ages:
            stale = sum(a > settings.stale_seconds for a in ages)
            print(
                f"- Возраст отметки на момент опроса: медиана {statistics.median(ages):.0f} с, "
                f"90% моложе {sorted(ages)[int(len(ages) * 0.9)]:.0f} с, "
                f"старше {settings.stale_seconds} с: {stale} ({100 * stale / len(ages):.0f}%)"
            )
        before = {v.vehicle.id: v for v in first}
        pairs = [(before[v.vehicle.id], v) for v in second if v.vehicle.id in before and v.on_line]
        changed = [
            (b.vehicle.position_observed_at - a.vehicle.position_observed_at).total_seconds()
            for a, b in pairs
            if b.vehicle.position_observed_at != a.vehicle.position_observed_at
        ]
        if pairs:
            print(
                f"- Через 30 с новая отметка у {len(changed)} из {len(pairs)} машин "
                f"({100 * len(changed) / len(pairs):.0f}%); шаг между отметками: медиана "
                f"{statistics.median(changed) if changed else 0:.0f} с"
            )
        ids_twice = Counter(v.vehicle.id for v in first)
        dup = sum(n > 1 for n in ids_twice.values())
        print(f"- Повторы id машины (вид-маршрут-выход) в одном опросе: {dup}")

        # Линии и остановки по всем маршрутам, оба направления.
        paths: dict[tuple[str, Direction], LinePath] = {}
        failed: list[str] = []
        for line in lines:
            for direction in Direction:
                try:
                    paths[(line.id, direction)] = await feed.line_path(line.id, direction)
                except (TransitFeedError, UnknownLineError) as exc:  # отчёт дойдёт до конца
                    failed.append(f"{line.id} {direction.value}: {exc}")
        stops = [s for p in paths.values() for s in p.stops]
        no_coords = sum(not (s.stop.point.lat and s.stop.point.lon) for s in stops)
        print(f"- Линий получено: {len(paths)} из {2 * len(lines)}; не пришли: {len(failed)}")
        for item in failed[:10]:
            print(f"  - {item}")
        print(
            f"- Остановок на линиях: {len(stops)}, уникальных id: "
            f"{len({s.stop.id for s in stops})}, без координат: {no_coords}"
        )
        empty = [k for k, p in paths.items() if not p.stops]
        print(f"- Линий без остановок: {len(empty)}")

        # segment_order против положения на линии.
        print("\n### segment_order и положение на линии\n")
        print(
            "| Машина | Направление | segment_order | Проехала остановок по положению "
            "| Расстояние до линии, м |"
        )
        print("|---|---|---|---|---|")
        checked = diffs = 0
        for live in on_line:
            path = paths.get((live.vehicle.line_id, live.vehicle.direction))
            if path is None or live.stops_passed is None or checked >= SEGMENT_SAMPLE:
                continue
            idx, dist = nearest_index(path, live.vehicle.point)
            passed = sum(s.point_index <= idx for s in path.stops)
            checked += 1
            diffs += abs(passed - live.stops_passed) <= 1
            print(
                f"| {live.vehicle.type.value} {live.vehicle.number} ({live.vehicle.id}) "
                f"| {live.vehicle.direction.value} | {live.stops_passed} | {passed} "
                f"| {dist:.0f} |"
            )
        print(f"\nСовпадение в пределах ±1: {diffs} из {checked}.")
        print(f"\nЗапросов к ЦУГАЭТ за замер: {feed.requests_made}.")
    finally:
        await feed.aclose()


if __name__ == "__main__":
    asyncio.run(main())
