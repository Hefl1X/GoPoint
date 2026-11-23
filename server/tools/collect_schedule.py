"""Проверка группы сохранённых HTTP-ответов и сборка снимка расписания ЦУГАЭТ."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import date
from pathlib import Path

import httpx
from pydantic import BaseModel

from app.adapters.tsugaet.parse import parse_routes
from app.adapters.tsugaet.schedule import (
    ScheduleBudget,
    ScheduleGroup,
    ScheduleSourceError,
    TsugaetScheduleSource,
    planned_requests,
)
from app.domain.gtfs import ServiceWindow, build_gtfs
from app.domain.models import Direction
from tools.build_gtfs import SAMPLES, write_snapshot

_CATALOG = httpx.URL("https://map.nskgortrans.ru/listmarsh.php?r=true")
_ARCHIVE_ENDPOINTS = frozenset(
    {"/listmarsh.php", "/trasses.php", "/components/com_planrasp/helpers/grasp.php"}
)
type GroupKey = tuple[str, Direction, str]


class _Response(BaseModel):
    file: str
    url: str
    status: int
    bytes: int
    sha256: str


class _Manifest(BaseModel):
    requests: list[_Response]


def _request_key(url: httpx.URL) -> tuple[str, tuple[tuple[str, str], ...]]:
    return str(url.copy_with(query=None)), tuple(sorted(url.params.multi_items()))


class _Archive:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        manifest = _Manifest.model_validate_json((directory / "manifest.json").read_bytes())
        self.entries: dict[tuple[str, tuple[tuple[str, str], ...]], _Response] = {}
        for row in manifest.requests:
            url = httpx.URL(row.url)
            if url.path in _ARCHIVE_ENDPOINTS:
                key = _request_key(url)
                if key in self.entries:
                    raise ValueError("Повторный URL расписания в архиве HTTP-ответов")
                self.entries[key] = row
        self.checksums: dict[str, str] = {}
        self.catalog_count = 0

    def response(self, request: httpx.Request) -> httpx.Response:
        key = _request_key(request.url)
        entry = self.entries.get(key)
        if entry is None:
            raise ValueError(f"В архиве отсутствует ответ для {request.url}")
        if Path(entry.file).name != entry.file:
            raise ValueError("Имя файла в архиве должно быть без каталога")
        data = (self.directory / entry.file).read_bytes()
        checksum = hashlib.sha256(data).hexdigest()
        if checksum != entry.sha256 or len(data) != entry.bytes:
            raise ValueError(f"Нарушена целостность архивного ответа {entry.file}")
        self.checksums[entry.file] = checksum
        return httpx.Response(entry.status, content=data)

    def groups(self, keys: tuple[GroupKey, ...]) -> tuple[ScheduleGroup, ...]:
        catalog = self.response(httpx.Request("GET", _CATALOG))
        if catalog.status_code != httpx.codes.OK:
            raise ValueError("Архивный каталог маршрутов недоступен")
        routes = {route.line_id: route for route in parse_routes(catalog.json())}
        self.catalog_count = len(routes)
        result: list[ScheduleGroup] = []
        for line_id, direction, day in keys:
            if line_id not in routes:
                raise ValueError(f"Маршрут отсутствует в архивном каталоге: {line_id}")
            result.append(ScheduleGroup(routes[line_id], direction, day))
        return tuple(result)


async def _skip_wait(_seconds: float) -> None:
    """Архив не обращается к HTTP-серверу."""


async def prepare_snapshot(
    archive_dir: Path,
    output: Path,
    keys: tuple[GroupKey, ...],
    window: ServiceWindow,
    budget: ScheduleBudget,
) -> bool:
    if output.exists():
        raise FileExistsError(f"Укажите новый каталог снимка: {output}")
    if not keys or len(set(keys)) != len(keys):
        raise ValueError("Укажите неповторяющиеся группы расписания")
    archive = _Archive(archive_dir)
    groups = archive.groups(keys)
    expected = planned_requests(groups)
    catalog = archive.entries[_request_key(_CATALOG)]
    if expected + 1 > budget.requests:
        raise ScheduleSourceError(f"Бюджет запросов меньше плана ({expected + 1})")
    if catalog.bytes >= budget.payload_bytes:
        raise ScheduleSourceError("Каталог исчерпал бюджет байтов")

    source_budget = ScheduleBudget(budget.requests - 1, budget.payload_bytes - catalog.bytes)
    async with httpx.AsyncClient(transport=httpx.MockTransport(archive.response)) as client:
        source = TsugaetScheduleSource(client, source_budget, sleep=_skip_wait)
        loaded = await source.load_many(groups)
    build = build_gtfs([(item.schedule, item.path) for item in loaded], window)
    write_snapshot(
        output,
        window,
        build,
        {
            "sources": archive.checksums,
            "collection": {
                "mode": "archive",
                "catalog_routes": archive.catalog_count,
                "selected_groups": len(groups),
                "planned_requests": expected + 1,
                "requests": source.requests_made + 1,
                "payload_bytes": source.payload_bytes + catalog.bytes,
            },
        },
    )
    return bool(build.tables)


def _group(text: str) -> GroupKey:
    try:
        line, direction, day = text.split(":")
        if not line or not day:
            raise ValueError
        return line, Direction(direction), day
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Ожидалась группа в виде bus-8:A:23") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=SAMPLES)
    parser.add_argument("--group", action="append", type=_group, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--service-start", type=date.fromisoformat, required=True)
    parser.add_argument("--service-end", type=date.fromisoformat, required=True)
    parser.add_argument("--max-requests", type=int, required=True)
    parser.add_argument("--max-bytes", type=int, required=True)
    args = parser.parse_args()
    try:
        ready = asyncio.run(
            prepare_snapshot(
                args.archive,
                args.output,
                tuple(args.group),
                ServiceWindow(args.service_start, args.service_end),
                ScheduleBudget(args.max_requests, args.max_bytes),
            )
        )
    except (OSError, ValueError, ScheduleSourceError) as exc:
        parser.exit(1, f"{exc}\n")
    if not ready:
        parser.exit(1, f"Нет пригодных групп. См. {args.output / 'coverage.json'}\n")
    print(json.dumps({"snapshot": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
