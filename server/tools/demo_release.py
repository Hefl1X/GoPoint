"""Подключить готовый транспортный комплект к обычному Docker-демо."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.adapters.otp.release import verify_release


def configure_demo(store: Path, version: str, today: date) -> Path:
    if len(version) != 64 or any(char not in "0123456789abcdef" for char in version):
        raise ValueError("Некорректный ID транспортного комплекта")
    release = store / "releases" / version
    manifest = verify_release(release)
    if not manifest.service_start <= today <= manifest.service_end:
        raise ValueError(
            f"Расписание действует {manifest.service_start}–{manifest.service_end}. "
            "Подготовьте комплект на дату показа: bash scripts/prepare-demo.sh ДАТА-КОНЦА"
        )
    config = {
        "server": {"apiProcessingTimeout": "10s"},
        "updaters": [
            {
                "type": "stop-time-updater",
                "feedId": feed_id,
                "url": f"http://server:8000/internal/gtfs-rt/{endpoint}?version={version}",
                "frequency": "10s",
                "fuzzyTripMatching": False,
            }
            for feed_id, endpoint in (("gopoint-all", "all"), ("gopoint-low", "low-floor"))
        ],
    }
    runtime = store / "runtime" / version
    runtime.mkdir(parents=True, exist_ok=True)
    target = runtime / "router-config.demo.json"
    target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        configure_demo(args.store, args.version, datetime.now(ZoneInfo("Asia/Novosibirsk")).date())
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Демо не запущено: {exc}\n")


if __name__ == "__main__":
    main()
