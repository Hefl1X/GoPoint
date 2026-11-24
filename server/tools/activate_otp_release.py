"""Контрольное переключение версий в отдельном Docker-проекте OTP."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.adapters.otp.release import ArtifactManifest, verify_release
from tools.build_otp_artifacts import local_otp_image

_VERSION = re.compile("[0-9a-f]{64}")
_CONFIG = Path(__file__).resolve().parents[2] / "otp/release/compose.yml"
_STATUS_QUERY = {"query": "{ feeds { feedId version } }"}
type Action = Literal["activate", "restart", "rollback", "stop"]


class ActivationError(RuntimeError):
    pass


class ReleaseState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    current: str | None = None
    previous: str | None = None
    pending: str | None = None


class ReleaseRuntime(Protocol):
    def load(self, directory: Path, manifest: ArtifactManifest) -> None: ...

    def stop(self) -> None: ...


def _release(store: Path, version: str, image: str) -> tuple[Path, ArtifactManifest]:
    if not _VERSION.fullmatch(version):
        raise ActivationError("ID версии должен быть SHA-256")
    path = store / "releases" / version
    return path, verify_release(path, otp_image=image)


def _read(store: Path) -> ReleaseState:
    path = store / "active.json"
    if not path.exists():
        return ReleaseState()
    state = ReleaseState.model_validate_json(path.read_bytes())
    if any(value and not _VERSION.fullmatch(value) for value in state.model_dump().values()):
        raise ActivationError("В active.json повреждён идентификатор версии")
    return state


def _write(store: Path, state: ReleaseState) -> None:
    with TemporaryDirectory(dir=store, prefix=".active-") as directory:
        staged = Path(directory) / "active.json"
        with staged.open("xb") as file:
            file.write((state.model_dump_json(indent=2) + "\n").encode())
            file.flush()
            os.fsync(file.fileno())
        staged.replace(store / "active.json")


def _restore(store: Path, state: ReleaseState, image: str, runtime: ReleaseRuntime) -> ReleaseState:
    if state.current is None:
        runtime.stop()
    else:
        runtime.load(*_release(store, state.current, image))
    restored = ReleaseState(current=state.current, previous=state.previous)
    _write(store, restored)
    return restored


def switch_release(
    store: Path,
    runtime: ReleaseRuntime,
    image: str,
    action: Action,
    version: str | None = None,
) -> ReleaseState:
    """Подтверждает указатель после загрузки двух фидов и сохраняет предыдущее состояние."""
    with (store / ".activate.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = _read(store)
        if action == "stop":
            runtime.stop()
            return state
        if state.pending is not None:
            state = _restore(store, state, image, runtime)
            if action == "restart":
                return state
        if action == "restart":
            if state.current is None:
                raise ActivationError("Активная версия ещё не выбрана")
            return _restore(store, state, image, runtime)
        if action == "rollback":
            version = state.previous
        if version is None:
            raise ActivationError("Нет версии для переключения")
        candidate = _release(store, version, image)
        if version == state.current:
            return state
        if action == "activate" and state.current is not None:
            _release(store, state.current, image)
        _write(store, state.model_copy(update={"pending": version}))
        try:
            runtime.load(*candidate)
            result = ReleaseState(current=version, previous=state.current)
            _write(store, result)
        except (RuntimeError, OSError, subprocess.SubprocessError, KeyboardInterrupt):
            _restore(store, state, image, runtime)
            raise
        return result


class _ServedFeed(BaseModel):
    feed_id: str = Field(alias="feedId")
    version: str | None


class _ServedData(BaseModel):
    feeds: list[_ServedFeed]


class _ServedResponse(BaseModel):
    data: _ServedData


@dataclass(frozen=True)
class _DockerRuntime:
    docker: str
    image: str
    store: Path
    port: int
    timeout_s: float

    def _compose(self, directory: Path, *args: str) -> None:
        store_key = hashlib.sha256(os.fsencode(self.store.resolve())).hexdigest()[:12]
        env = {
            **os.environ,
            "GOPOINT_OTP_RELEASE_DIR": str(directory.resolve()),
            "GOPOINT_OTP_RELEASE_IMAGE": self.image,
            "GOPOINT_OTP_RELEASE_PORT": str(self.port),
        }
        subprocess.run(  # noqa: S603 — аргументы выделенного локального Compose-проекта
            [
                self.docker,
                "compose",
                "--env-file",
                "/dev/null",
                "-p",
                f"gopoint-otp-release-{store_key}",
                "-f",
                str(_CONFIG),
                *args,
            ],
            env=env,
            check=True,
        )

    def stop(self) -> None:
        self._compose(self.store, "down")

    def load(self, directory: Path, manifest: ArtifactManifest) -> None:
        self._compose(directory, "up", "-d", "--force-recreate")
        expected = dict.fromkeys(manifest.feeds.values(), manifest.version)
        deadline = time.monotonic() + self.timeout_s
        url = f"http://127.0.0.1:{self.port}/otp/gtfs/v1"
        with httpx.Client(trust_env=False, timeout=2.0) as client:
            while time.monotonic() < deadline:
                try:
                    response = client.post(url, json=_STATUS_QUERY)
                    response.raise_for_status()
                except httpx.HTTPError:
                    time.sleep(0.5)
                    continue
                try:
                    served = _ServedResponse.model_validate_json(response.content).data.feeds
                except ValueError as exc:
                    raise ActivationError("OTP не вернул версии обоих фидов") from exc
                if (
                    len(served) != len(expected)
                    or {feed.feed_id: feed.version for feed in served} != expected
                ):
                    raise ActivationError("Загруженные фиды OTP не совпадают с manifest.json")
                return
        raise ActivationError("OTP не подтвердил готовность загрузки")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18801)
    parser.add_argument("--timeout", type=float, default=25.0)
    actions = parser.add_subparsers(dest="action", required=True)
    activate = actions.add_parser("activate")
    activate.add_argument("version")
    actions.add_parser("rollback")
    actions.add_parser("restart")
    actions.add_parser("stop")
    args = parser.parse_args()
    try:
        docker, image = local_otp_image()
        runtime = _DockerRuntime(docker, image, args.store, args.port, args.timeout)
        state = switch_release(
            args.store, runtime, image, args.action, getattr(args, "version", None)
        )
        print(json.dumps(state.model_dump(), ensure_ascii=False))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
