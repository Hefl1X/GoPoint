"""Ограниченная инвентаризация каталога, направлений и типов дней ЦУГАЭТ."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from app.adapters.tsugaet.feed import TRASSES_BATCH
from app.adapters.tsugaet.parse import RouteInfo, TsugaetFormatError, parse_routes
from app.adapters.tsugaet.schedule import (
    MetadataReply,
    ScheduleBudget,
    ScheduleBudgetError,
    ScheduleSourceError,
    TsugaetScheduleSource,
)
from app.adapters.tsugaet.schedule_parse import (
    ScheduleDayMetadata,
    parse_schedule_days,
    parse_schedule_directions,
)
from app.domain.models import Direction
from tools.collect_schedule import ScheduleArchive

MAX_REQUESTS = 320
_MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class _Capture:
    file: str
    url: str
    status: int
    bytes: int
    sha256: str


@dataclass(frozen=True)
class _Direction:
    direction: Direction
    days: tuple[ScheduleDayMetadata, ...]


@dataclass(frozen=True)
class _Route:
    line_id: str
    directions: tuple[_Direction, ...]


@dataclass(frozen=True)
class _Issue:
    scope: str
    error: str


@dataclass
class _Inventory:
    catalog_routes: int = 0
    routes: list[_Route] = field(default_factory=list)
    issues: list[_Issue] = field(default_factory=list)

    def report(self) -> dict[str, object]:
        directions = [direction for route in self.routes for direction in route.directions]
        days = [day for direction in directions for day in direction.days]
        geometry = sum(
            (
                sum(item.direction == direction and bool(item.days) for item in directions)
                + TRASSES_BATCH
                - 1
            )
            // TRASSES_BATCH
            for direction in Direction
        )
        complete = (
            self.catalog_routes > 0 and len(self.routes) == self.catalog_routes and not self.issues
        )
        metadata = 1 + self.catalog_routes + len(directions)
        return {
            "complete": complete,
            "catalog_routes": self.catalog_routes,
            "directions": len(directions),
            "empty_directions": sum(not direction.days for direction in directions),
            "groups": len(days),
            "supported_groups": sum(day.kind is not None for day in days),
            "geometry_batches": geometry,
            "full_requests_without_retries": metadata + 2 * len(days) + geometry
            if complete
            else None,
            "routes": [asdict(route) for route in self.routes],
            "issues": [asdict(issue) for issue in self.issues],
        }


class _Output:
    def __init__(self, path: Path) -> None:
        path.mkdir(parents=True)
        self.path = path
        self.captures: list[_Capture] = []

    def save(self, name: str, reply: MetadataReply) -> bytes:
        target = self.path / name
        target.write_bytes(reply.body)
        self.captures.append(
            _Capture(name, reply.url, 200, len(reply.body), hashlib.sha256(reply.body).hexdigest())
        )
        return reply.body

    def write_json(self, filename: str, data: object) -> None:
        target = self.path / filename
        staged = target.with_suffix(".tmp")
        staged.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        staged.replace(target)


async def _directions(
    route: RouteInfo,
    index: int,
    source: TsugaetScheduleSource,
    output: _Output,
    inventory: _Inventory,
) -> tuple[_Direction, ...]:
    try:
        reply = await source.directions_metadata(route)
        body = output.save(f"directions-{index:03}.xml", reply)
        directions = parse_schedule_directions(body.decode("utf-8"))
    except ScheduleBudgetError:
        raise
    except (ScheduleSourceError, ValueError) as exc:
        inventory.issues.append(_Issue(route.line_id, str(exc)))
        return ()

    result: list[_Direction] = []
    for direction in directions:
        try:
            reply = await source.days_metadata(route, direction)
            body = output.save(f"days-{index:03}-{direction.value}.xml", reply)
            days = parse_schedule_days(body.decode("utf-8"))
            result.append(_Direction(direction, days))
        except ScheduleBudgetError:
            raise
        except (ScheduleSourceError, ValueError) as exc:
            inventory.issues.append(_Issue(f"{route.line_id}:{direction.value}", str(exc)))
    return tuple(result)


async def _scan(
    source: TsugaetScheduleSource, output: _Output, inventory: _Inventory, *, progress: bool
) -> None:
    catalog = output.save("listmarsh.json", await source.catalog_metadata())
    routes = sorted(parse_routes(json.loads(catalog)), key=lambda route: route.line_id)
    if not routes or len({route.line_id for route in routes}) != len(routes):
        raise TsugaetFormatError("Каталог пуст или содержит повторный идентификатор маршрута")
    inventory.catalog_routes = len(routes)
    for index, route in enumerate(routes, start=1):
        directions = await _directions(route, index, source, output, inventory)
        inventory.routes.append(_Route(route.line_id, directions))
        if progress and index % 20 == 0:
            print(f"Маршруты: {index}/{len(routes)}; запросы: {source.requests_made}", flush=True)


async def inventory(
    source: TsugaetScheduleSource, output_dir: Path, *, progress: bool = False
) -> dict[str, object]:
    output = _Output(output_dir)
    result = _Inventory()
    try:
        await _scan(source, output, result, progress=progress)
    except (ScheduleSourceError, ValueError) as exc:
        result.issues.append(_Issue("inventory", str(exc)))
    finally:
        output.write_json("manifest.json", {"requests": [asdict(item) for item in output.captures]})
        report = result.report() | {
            "requests": source.requests_made,
            "payload_bytes": source.payload_bytes,
            "captured_responses": len(output.captures),
        }
        output.write_json("inventory.json", report)
    return report


async def _skip_wait(_seconds: float) -> None:
    """Повтор из архива не обращается к серверу."""


async def _run(output: Path, budget: ScheduleBudget, archive_dir: Path | None) -> int:
    transport = None
    if archive_dir is not None:
        transport = httpx.MockTransport(ScheduleArchive(archive_dir).response)
    async with httpx.AsyncClient(
        timeout=10.0,
        headers={"User-Agent": "GoPoint/0.1 (schedule metadata inventory)"},
        transport=transport,
    ) as client:
        if archive_dir is None:
            source = TsugaetScheduleSource(client, budget)
        else:
            source = TsugaetScheduleSource(client, budget, sleep=_skip_wait)
        report = await inventory(source, output, progress=archive_dir is None)
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "routes"}, ensure_ascii=False
        )
    )
    return 0 if report["complete"] else 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-requests", type=int, default=MAX_REQUESTS)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--capture", action="store_true")
    mode.add_argument("--archive", type=Path)
    args = parser.parse_args(argv)
    if not 1 <= args.max_requests <= MAX_REQUESTS:
        parser.error(f"Лимит должен быть от 1 до {MAX_REQUESTS} запросов")
    try:
        return asyncio.run(
            _run(args.output, ScheduleBudget(args.max_requests, _MAX_BYTES), args.archive)
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
