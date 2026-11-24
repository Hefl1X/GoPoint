"""Сохранить согласованную часовую GPS-серию автобуса №8 и маршрутки №35."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.adapters.tsugaet.gps_capture import capture_markers

GPS_URL = httpx.URL("https://map.nskgortrans.ru/markers.php", params={"r": "1-8-W-8|8-35-W-35|"})
ROUTES = ("bus-8", "minibus-35")
INTERVAL_S = 30
DURATION_S = 3600
MAX_REQUESTS = 120
MAX_BYTES = 5_000_000


@dataclass(frozen=True)
class GpsSample:
    started_at: str
    received_at: str
    status: int | None
    size: int
    issue: str | None
    file: str | None = None
    sha256: str | None = None


@dataclass
class GpsSeries:
    started_at: str
    ended_at: str | None = None
    reason: str | None = None
    requests: list[GpsSample] = field(default_factory=list)

    def write(self, output: Path) -> None:
        path = output / "manifest.json"
        staged = path.with_suffix(".tmp")
        staged.write_text(
            json.dumps(
                {
                    "url": str(GPS_URL),
                    "routes": ROUTES,
                    "interval_s": INTERVAL_S,
                    "duration_s": DURATION_S,
                    "max_requests": MAX_REQUESTS,
                    "max_bytes": MAX_BYTES,
                    **asdict(self),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        staged.replace(path)


async def capture(client: httpx.AsyncClient, output: Path) -> GpsSeries:
    output.mkdir(parents=True)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + DURATION_S
    series = GpsSeries(datetime.now(UTC).isoformat())
    remaining = MAX_BYTES
    next_at = loop.time()
    series.write(output)
    try:
        for sequence in range(1, MAX_REQUESTS + 1):
            await asyncio.sleep(max(0.0, min(deadline, next_at) - loop.time()))
            began = loop.time()
            if began >= deadline:
                break
            next_at = began + INTERVAL_S
            started_at = datetime.now(UTC).isoformat()
            reply = await capture_markers(
                client, GPS_URL, max_bytes=remaining, timeout_s=min(10, deadline - began)
            )
            received_at = datetime.now(UTC).isoformat()
            remaining -= len(reply.body)
            name, checksum = None, None
            if reply.issue is None:
                name = f"markers-{sequence:03}.json"
                (output / name).write_bytes(reply.body)
                checksum = hashlib.sha256(reply.body).hexdigest()
            series.requests.append(
                GpsSample(
                    started_at,
                    received_at,
                    reply.status,
                    len(reply.body),
                    reply.issue,
                    name,
                    checksum,
                )
            )
            series.write(output)
            if sequence == 1 or sequence % 20 == 0:
                print(f"GPS: {sequence}/{MAX_REQUESTS}, {MAX_BYTES - remaining} байт", flush=True)
            if reply.issue == "byte_limit" or remaining == 0:
                series.reason = "byte_limit"
                break
            if reply.status in {401, 403, 429}:
                series.reason = "source_refused"
                break
        if series.reason is None:
            await asyncio.sleep(max(0.0, deadline - loop.time()))
            series.reason = "duration"
    finally:
        series.ended_at = datetime.now(UTC).isoformat()
        series.write(output)
    return series


async def _run(output: Path) -> int:
    headers = {"User-Agent": "GoPoint/0.1 (bounded GPS series)", "Accept-Encoding": "identity"}
    async with httpx.AsyncClient(
        headers=headers, follow_redirects=False, trust_env=False
    ) as client:
        series = await capture(client, output)
    successful = sum(sample.file is not None for sample in series.requests)
    print(f"{series.reason}: {successful}/{len(series.requests)} ответов; {output}")
    return 0 if series.reason == "duration" and successful else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return asyncio.run(_run(args.output))


if __name__ == "__main__":
    raise SystemExit(main())
