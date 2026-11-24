"""Подготовить согласованный граф и конфигурацию updater для проверки в Docker."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory
from typing import TypedDict, cast
from urllib.parse import urlencode

from app.adapters.otp.release import verify_release


class _Updater(TypedDict):
    url: str


def prepare(release: Path, directory: Path) -> str:
    manifest = verify_release(release)
    destination = directory / "releases" / manifest.version
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=destination.parent, prefix=".rt-") as temporary:
            staged = Path(temporary) / manifest.version
            copytree(release, staged)
            verify_release(staged)
            staged.rename(destination)
    else:
        verify_release(destination)
    config = cast(
        dict[str, object],
        json.loads(Path(__file__).with_name("router-config.json").read_bytes()),
    )
    for updater in cast(list[_Updater], config["updaters"]):
        updater["url"] = f"{updater['url']}?{urlencode({'version': manifest.version})}"
    runtime = directory / "runtime" / manifest.version
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "router-config.json").write_text(json.dumps(config, indent=2) + "\n", "utf-8")
    scenario = directory / "scenario"
    scenario.mkdir(exist_ok=True)
    if not (scenario / "step").exists():
        (scenario / "step").write_text("0\n", "ascii")
    return manifest.version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(prepare(args.release, args.directory))
