"""Собрать пилотный GTFS с трассировкой к сохранённым ответам ЦУГАЭТ."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZipInfo

from pydantic import BaseModel, TypeAdapter, ValidationError

from app.adapters.tsugaet.parse import TsugaetFormatError, parse_routes, parse_traces
from app.adapters.tsugaet.schedule_parse import parse_route_schedule
from app.domain.gtfs import (
    GtfsBuild,
    GtfsBuildError,
    GtfsTable,
    ServiceCoverage,
    ServiceWindow,
    build_gtfs,
)
from app.domain.models import Direction, LinePath, TransportType
from app.domain.schedule import RouteSchedule, ScheduleRoute

SAMPLES = Path(__file__).resolve().parents[2] / "data/tsugaet/samples/audit-2026-11-21"
_PILOT = (
    ("bus8", TransportType.BUS, "8", "23"),
    ("minibus35", TransportType.MINIBUS, "35", "23"),
    ("tram13", TransportType.TRAM, "0013", "11"),
)
_COVERAGE = TypeAdapter(tuple[ServiceCoverage, ...])


class _Capture(BaseModel):
    file: str
    status: int
    sha256: str


class _Manifest(BaseModel):
    requests: list[_Capture]


class _Samples:
    def __init__(self, root: Path) -> None:
        self.root = root
        manifest = _Manifest.model_validate_json((root / "manifest.json").read_bytes())
        self._captures = {item.file: item for item in manifest.requests}
        if len(self._captures) != len(manifest.requests):
            raise TsugaetFormatError("Повторное имя ответа в manifest.json")
        self.checksums: dict[str, str] = {}

    def read(self, name: str) -> str:
        capture = self._captures.get(name)
        if capture is None or capture.status != 200:
            raise TsugaetFormatError(f"В manifest.json нет успешного ответа {name}")
        data = (self.root / name).read_bytes()
        checksum = hashlib.sha256(data).hexdigest()
        if checksum != capture.sha256:
            raise TsugaetFormatError(f"Контрольная сумма не совпала для {name}")
        self.checksums[name] = checksum
        return data.decode("utf-8")


def _build_pilot(samples: _Samples, window: ServiceWindow) -> GtfsBuild:
    routes = {
        (route.type, route.marsh): route
        for route in parse_routes(json.loads(samples.read("listmarsh.json")))
    }
    wanted = []
    for _, type_, marsh, _ in _PILOT:
        catalog_entry = routes.get((type_, marsh))
        if catalog_entry is None:
            raise TsugaetFormatError(f"Маршрут {type_.value}/{marsh} отсутствует в каталоге")
        wanted.append((catalog_entry.line_id, marsh))
    paths = parse_traces(json.loads(samples.read("trasses-A.json")), wanted, Direction.A)

    sources: list[tuple[RouteSchedule, LinePath | None]] = []
    for name, type_, marsh, day_id in _PILOT:
        route = ScheduleRoute(type_, marsh, routes[type_, marsh].name, Direction.A)
        schedule = parse_route_schedule(
            samples.read(f"{name}-A-day{day_id}-all.html"),
            samples.read(f"{name}-A-stops.xml"),
            samples.read(f"{name}-A-days.xml"),
            route=route,
            day_id=day_id,
        )
        sources.append((schedule, paths.get(route.line_id)))
    return build_gtfs(sources, window)


def _write_gtfs(path: Path, tables: tuple[GtfsTable, ...]) -> None:
    with ZipFile(path, "w") as archive:
        for table in tables:
            with io.StringIO(newline="") as stream:
                writer = csv.writer(stream, lineterminator="\n")
                writer.writerow(table.header)
                writer.writerows(table.rows)
                archive.writestr(ZipInfo(table.name), stream.getvalue().encode("utf-8"))


def build_pilot(samples_dir: Path, output: Path, window: ServiceWindow) -> GtfsBuild:
    if output.exists():
        raise FileExistsError(f"Укажите новый каталог для результата: {output}")
    samples = _Samples(samples_dir)
    build = _build_pilot(samples, window)
    report = {
        "service_start": window.start.isoformat(),
        "service_end": window.end.isoformat(),
        "sources": samples.checksums,
        "coverage": _COVERAGE.dump_python(build.coverage, mode="json"),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".gtfs-", dir=output.parent) as workdir:
        staging = Path(workdir) / "pilot"
        staging.mkdir()
        if build.tables:
            _write_gtfs(staging / "schedule.gtfs.zip", build.tables)
        (staging / "coverage.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staging.rename(output)
    return build


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, default=SAMPLES)
    parser.add_argument("--output", type=Path, required=True, help="Новый каталог для ZIP и отчёта")
    parser.add_argument("--service-start", type=date.fromisoformat, required=True)
    parser.add_argument("--service-end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    try:
        window = ServiceWindow(args.service_start, args.service_end)
        build = build_pilot(args.samples, args.output, window)
    except (OSError, GtfsBuildError, TsugaetFormatError, ValidationError, UnicodeError) as exc:
        parser.exit(1, f"{exc}\n")
    if not build.tables:
        parser.exit(1, f"Нет групп для GTFS, см. {args.output / 'coverage.json'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
