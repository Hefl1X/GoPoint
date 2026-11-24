"""Ограниченный сбор таблиц и геометрии по проверенному архиву метаданных."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx
from pydantic import BaseModel

from app.adapters.tsugaet.schedule import (
    MetadataReply,
    ScheduleBudget,
    ScheduleBudgetError,
    ScheduleGroup,
    ScheduleSourceError,
    TsugaetScheduleSource,
    content_requests,
)
from app.domain.models import Direction
from tools.collect_schedule import ScheduleArchive
from tools.inventory_schedule import CaptureArchive

MAX_REQUESTS = 650
MAX_BYTES = 60_000_000


class _Day(BaseModel):
    source_id: str


class _Direction(BaseModel):
    direction: Direction
    days: list[_Day]


class _Route(BaseModel):
    line_id: str
    directions: list[_Direction]


class _Inventory(BaseModel):
    complete: bool
    groups: int
    captured_responses: int
    full_requests_without_retries: int | None
    routes: list[_Route]


def inventory_groups(directory: Path, archive: ScheduleArchive) -> tuple[ScheduleGroup, ...]:
    inventory = _Inventory.model_validate_json((directory / "inventory.json").read_bytes())
    if not inventory.complete or inventory.captured_responses != len(archive.entries):
        raise ValueError("Нужна завершённая инвентаризация метаданных")
    keys = tuple(
        (route.line_id, direction.direction, day.source_id)
        for route in inventory.routes
        for direction in route.directions
        for day in direction.days
    )
    if not keys or len(keys) != inventory.groups or len(set(keys)) != len(keys):
        raise ValueError("Список групп не совпадает с итогом инвентаризации")
    groups = archive.groups(keys)
    if (
        len(content_requests(groups)) + len(archive.entries)
        != inventory.full_requests_without_retries
    ):
        raise ValueError("План запросов не совпадает с итогом инвентаризации")
    return groups


async def capture(
    source: TsugaetScheduleSource,
    metadata_dir: Path,
    output_dir: Path,
    *,
    progress: bool = False,
) -> dict[str, object]:
    archive = ScheduleArchive(metadata_dir)
    plan = content_requests(inventory_groups(metadata_dir, archive))
    saved = CaptureArchive(output_dir)
    network_responses = 0
    issues: list[dict[str, str]] = []
    try:
        for entry in archive.entries.values():
            body = archive.response(httpx.Request("GET", entry.url))
            if body.status_code != httpx.codes.OK:
                raise ValueError("В архиве есть неуспешный ответ метаданных")
            saved.save(entry.file, MetadataReply(entry.url, body.content))

        for index, request in enumerate(plan, start=1):
            try:
                reply = await source.capture_content(request)
            except ScheduleBudgetError as exc:
                issues.append({"kind": "budget", "error": str(exc)})
                break
            except ScheduleSourceError as exc:
                issues.append(
                    {
                        "kind": request.kind,
                        "url": str(httpx.URL(request.url, params=request.params)),
                        "error": str(exc),
                    }
                )
                continue
            extension = {"stops": "xml", "table": "html", "geometry": "json"}[request.kind]
            saved.save(f"{request.kind}-{index:03}.{extension}", reply)
            network_responses += 1
            if progress and index % 50 == 0:
                print(
                    f"План: {index}/{len(plan)}; запросы: {source.requests_made}; "
                    f"байты: {source.payload_bytes}",
                    flush=True,
                )
    finally:
        saved.write_manifest()
        report = {
            "complete": network_responses == len(plan),
            "planned_network_requests": len(plan),
            "network_requests": source.requests_made,
            "network_responses": network_responses,
            "network_payload_bytes": source.payload_bytes,
            "reused_metadata": len(saved.captures) - network_responses,
            "issues": issues,
        }
        saved.write_json("collection.json", report)
    return report


async def _run(metadata: Path, output: Path, budget: ScheduleBudget) -> int:
    async with httpx.AsyncClient(
        timeout=10.0,
        headers={"User-Agent": "GoPoint/0.1 (schedule and geometry inventory)"},
    ) as client:
        result = await capture(
            TsugaetScheduleSource(client, budget), metadata, output, progress=True
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["complete"] else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    try:
        groups = inventory_groups(args.metadata, ScheduleArchive(args.metadata))
        count = len(content_requests(groups))
        if count > MAX_REQUESTS:
            raise ValueError(f"План {count} превышает лимит {MAX_REQUESTS}")
        if args.plan:
            print(json.dumps({"groups": len(groups), "network_requests_without_retries": count}))
            return 0
        if args.output is None:
            parser.error("Для сбора нужен новый каталог --output")
        return asyncio.run(
            _run(args.metadata, args.output, ScheduleBudget(MAX_REQUESTS, MAX_BYTES))
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
