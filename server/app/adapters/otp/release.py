"""Формат и проверка сохранённой версии графа OTP."""

import hashlib
import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict

FEEDS = {"all.gtfs.zip": "gopoint-all", "low.gtfs.zip": "gopoint-low"}
RELEASE_FILES = frozenset({"graph.obj", "build-config.json", "coverage.json", *FEEDS})


class ArtifactError(ValueError):
    pass


class ArtifactManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    schedule_sha256: str
    street_key: str
    otp_image: str
    service_start: date
    service_end: date
    feeds: dict[str, str]
    sha256: dict[str, str]


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def file_digest(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def checked_digest(path: Path) -> str:
    if not path.is_file() or path.stat().st_size == 0:
        raise ArtifactError(f"Нет результата OTP: {path.name}")
    return file_digest(path)


def verify_release(release: Path, *, otp_image: str | None = None) -> ArtifactManifest:
    manifest = ArtifactManifest.model_validate_json((release / "manifest.json").read_bytes())
    version = hashlib.sha256(
        canonical_json([manifest.street_key, manifest.schedule_sha256])
    ).hexdigest()
    if (
        release.name != manifest.version
        or manifest.version != version
        or set(manifest.sha256) != RELEASE_FILES
        or manifest.sha256["all.gtfs.zip"] != manifest.sha256["low.gtfs.zip"]
        or manifest.feeds != FEEDS
        or (otp_image is not None and manifest.otp_image != otp_image)
    ):
        raise ArtifactError("Версия, состав или образ OTP не совпадают с manifest.json")
    for name, sha256 in manifest.sha256.items():
        if checked_digest(release / name) != sha256:
            raise ArtifactError(f"Не совпала контрольная сумма: {name}")
    return manifest
