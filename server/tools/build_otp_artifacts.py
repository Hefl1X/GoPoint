"""Офлайн-сборка неизменяемых версий OTP из проверенного расписания и OSM."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import shutil
import subprocess
from collections.abc import Callable
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile, ZipInfo

from app.adapters.otp.release import (
    FEEDS,
    RELEASE_FILES,
    ArtifactError,
    ArtifactManifest,
    canonical_json,
    checked_digest,
    file_digest,
    verify_release,
)
from app.adapters.otp.schedule import (
    binding_data,
    load_release_schedule,
    published_coverage,
    read_published_schedule,
)
from app.domain.gtfs import ServiceWindow

OTP_IMAGE = "opentripplanner/opentripplanner:2.10.0"
DEFAULT_BUILD_CONFIG = Path(__file__).resolve().parents[2] / "otp/build-config.json"
STREET_FILE = "streetGraph.obj"
GTFS_FILES = frozenset(
    {
        "agency.txt",
        "stops.txt",
        "routes.txt",
        "trips.txt",
        "stop_times.txt",
        "calendar.txt",
        "feed_info.txt",
    }
)
type Build = Callable[[Path, tuple[str, ...]], None]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_schedule(path: Path) -> tuple[dict[str, bytes], dict[str, str], ServiceWindow]:
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or not set(names).issuperset(GTFS_FILES):
            raise ArtifactError("Некорректный состав исходного GTFS")
        tables = {name: archive.read(name) for name in sorted(names)}
    rows = list(csv.DictReader(io.StringIO(tables.pop("feed_info.txt").decode("utf-8"))))
    if len(rows) != 1:
        raise ArtifactError("Ожидалась одна запись в feed_info.txt")
    info = rows[0]
    info.pop("feed_version", None)
    window = ServiceWindow(
        date.fromisoformat(info["feed_start_date"]), date.fromisoformat(info["feed_end_date"])
    )
    return tables, info, window


def _write_feed(path: Path, tables: dict[str, bytes], info: dict[str, str], version: str) -> None:
    with ZipFile(path, "w") as archive, io.StringIO(newline="") as stream:
        row = dict(info, feed_version=version)
        writer = csv.DictWriter(stream, tuple(sorted(row)), lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
        archive.writestr(ZipInfo("feed_info.txt"), stream.getvalue().encode())
        for name, data in tables.items():
            archive.writestr(ZipInfo(name), data)


def _street_graph(
    cache: Path, osm: Path, osm_sha: str, config: dict[str, object], build: Build
) -> Path:
    output = cache / STREET_FILE
    checksum = cache / "sha256"
    if cache.exists():
        if checked_digest(output) != checksum.read_text(encoding="ascii").strip():
            raise ArtifactError("Повреждён кэш streetGraph.obj")
        return output

    with TemporaryDirectory(prefix=".street-", dir=cache.parent) as workdir:
        staging = Path(workdir) / "graph"
        staging.mkdir()
        source = staging / "novosibirsk.osm.pbf"
        shutil.copyfile(osm, source)
        if file_digest(source) != osm_sha:
            raise ArtifactError("Входной OSM изменился во время копирования")
        (staging / "build-config.json").write_bytes(canonical_json(config))
        build(staging, ("--buildStreet",))
        (staging / checksum.name).write_text(
            checked_digest(staging / STREET_FILE) + "\n", encoding="ascii"
        )
        source.unlink()
        staging.rename(cache)
    return output


def prepare_release(
    store: Path,
    osm: Path,
    schedule_dir: Path,
    street_options: dict[str, object],
    otp_image: str,
    build: Build,
) -> Path:
    tables, info, window = _read_schedule(schedule_dir / "schedule.gtfs.zip")
    coverage = (schedule_dir / "coverage.json").read_bytes()
    bindings = binding_data(published_coverage(coverage, window))
    schedule_sha = _digest(
        canonical_json(
            [info, {name: _digest(data) for name, data in tables.items()}, _digest(bindings)]
        )
    )
    osm_sha = file_digest(osm)
    street_config = {
        key: value
        for key, value in street_options.items()
        if key not in {"transitFeeds", "transitServiceStart", "transitServiceEnd"}
    } | {"transitFeeds": []}
    street_key = _digest(canonical_json([otp_image, osm_sha, street_config]))
    version = _digest(canonical_json([street_key, schedule_sha]))

    cache = store / "street"
    releases = store / "releases"
    cache.mkdir(parents=True, exist_ok=True)
    releases.mkdir(exist_ok=True)
    release = releases / version
    with (store / ".build.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if release.exists():
            verify_release(release, otp_image=otp_image)
            return release
        street_graph = _street_graph(cache / street_key, osm, osm_sha, street_config, build)
        _build_release(
            release,
            street_graph,
            tables,
            info,
            coverage,
            street_config,
            ArtifactManifest(
                version=version,
                schedule_sha256=schedule_sha,
                street_key=street_key,
                otp_image=otp_image,
                service_start=window.start,
                service_end=window.end,
                feeds=FEEDS,
                sha256={},
            ),
            build,
        )
    return release


def _build_release(
    release: Path,
    street_graph: Path,
    tables: dict[str, bytes],
    info: dict[str, str],
    coverage: bytes,
    street_config: dict[str, object],
    manifest: ArtifactManifest,
    build: Build,
) -> None:
    with TemporaryDirectory(prefix=".release-", dir=release.parent) as workdir:
        staging = Path(workdir) / release.name
        staging.mkdir()
        street_input = staging / STREET_FILE
        shutil.copyfile(street_graph, street_input)
        street_sha = file_digest(street_graph)
        for name in FEEDS:
            _write_feed(staging / name, tables, info, manifest.version)
        read_published_schedule(
            staging / "all.gtfs.zip",
            coverage,
            manifest.version,
            ServiceWindow(manifest.service_start, manifest.service_end),
        )
        config = street_config | {
            "osm": [],
            "transitServiceStart": manifest.service_start.isoformat(),
            "transitServiceEnd": manifest.service_end.isoformat(),
            "transitFeeds": [
                {"type": "gtfs", "source": name, "feedId": feed} for name, feed in FEEDS.items()
            ],
        }
        (staging / "build-config.json").write_bytes(canonical_json(config))
        (staging / "coverage.json").write_bytes(coverage)
        build(staging, ("--loadStreet", "--save"))
        if file_digest(street_input) != street_sha:
            raise ArtifactError("OTP изменил промежуточный streetGraph.obj")
        street_input.unlink()
        checksums = {name: checked_digest(staging / name) for name in sorted(RELEASE_FILES)}
        complete = manifest.model_copy(update={"sha256": checksums})
        (staging / "manifest.json").write_text(
            complete.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        verify_release(staging, otp_image=manifest.otp_image)
        staging.rename(release)


def local_otp_image() -> tuple[str, str]:
    docker = shutil.which("docker")
    if docker is None:
        raise ArtifactError("Docker CLI не найден")
    result = subprocess.run(  # noqa: S603 — локальный образ OTP указан в коде
        [docker, "image", "inspect", "--format", "{{.Id}}", OTP_IMAGE],
        check=True,
        capture_output=True,
        text=True,
    )
    return docker, result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    prepare = actions.add_parser("prepare")
    prepare.add_argument("--store", type=Path, required=True)
    prepare.add_argument("--osm", type=Path, required=True)
    prepare.add_argument("--schedule", type=Path, required=True)
    prepare.add_argument("--java-options", default="-Xmx3g")
    verify = actions.add_parser("verify")
    verify.add_argument("release", type=Path)
    args = parser.parse_args()
    try:
        docker, image = local_otp_image()
        if args.action == "verify":
            print(load_release_schedule(args.release, otp_image=image).version)
            return 0
        options = json.loads(DEFAULT_BUILD_CONFIG.read_bytes())

        def build(path: Path, switches: tuple[str, ...]) -> None:
            subprocess.run(  # noqa: S603 — локальные входы, аргументы без shell
                [
                    docker,
                    "run",
                    "--rm",
                    "--pull",
                    "never",
                    "--network",
                    "none",
                    "-e",
                    f"JAVA_TOOL_OPTIONS={args.java_options}",
                    "--mount",
                    f"type=bind,src={path.resolve()},dst=/var/opentripplanner",
                    image,
                    *switches,
                ],
                check=True,
            )

        print(prepare_release(args.store, args.osm, args.schedule, options, image, build))
    except (
        OSError,
        ValueError,
        KeyError,
        BadZipFile,
        subprocess.CalledProcessError,
    ) as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
