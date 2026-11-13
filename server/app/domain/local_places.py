"""Свои подсказки поиска: синонимы мест (НГУ, вокзал) и остановки ЦУГАЭТ.

Photon ищет слова из названия на карте и не знает сокращений и разговорных имён.
Синонимы лежат в файле `data/geocoder/aliases_nsk.csv`: правим файл, не код.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from app.domain.geo import distance_m
from app.domain.models import LatLon, PlaceKind, PlaceSuggestion, Stop
from app.domain.search import DUPLICATE_RADIUS_M, normalize_query

# Короче этого запрос должен совпасть с именем целиком, иначе «нгу» тянул бы всё подряд.
MIN_PREFIX_LENGTH = 4

_WORD = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class Alias:
    names: tuple[str, ...]  # как человек может назвать место, уже нормализованные
    place: PlaceSuggestion


def load_aliases(path: Path) -> list[Alias]:
    """Читает файл синонимов: names (через |), title, subtitle, kind, lat, lon."""
    aliases: list[Alias] = []
    with path.open(encoding="utf-8", newline="") as file:
        for number, row in enumerate(csv.DictReader(file), start=1):
            names = tuple(normalize_query(n) for n in row["names"].split("|") if n.strip())
            place = PlaceSuggestion(
                id=f"alias-{number}",
                title=row["title"].strip(),
                subtitle=row["subtitle"].strip() or None,
                kind=PlaceKind(row["kind"].strip()),
                point=LatLon(lat=float(row["lat"]), lon=float(row["lon"])),
            )
            aliases.append(Alias(names=names, place=place))
    return aliases


def match_aliases(query: str, aliases: list[Alias]) -> list[PlaceSuggestion]:
    """Места, чьё имя совпало с запросом целиком (или начинается с него от 4 букв)."""
    q = normalize_query(query)
    found: list[PlaceSuggestion] = []
    for alias in aliases:
        if any(
            name == q or (len(q) >= MIN_PREFIX_LENGTH and name.startswith(q))
            for name in alias.names
        ):
            found.append(alias.place)
    return found


def match_stops(
    query: str, stops: list[Stop], near: LatLon, *, limit: int
) -> list[PlaceSuggestion]:
    """Остановки, у которых каждое слово запроса — начало какого-то слова названия.

    Ближайшие к `near` первыми; одноимённые остановки рядом (две стороны улицы) — одна.
    """
    words = _WORD.findall(normalize_query(query))
    if not words:
        return []
    matching = [
        s
        for s in stops
        if (name_words := _WORD.findall(normalize_query(s.name)))
        and all(any(nw.startswith(w) for nw in name_words) for w in words)
    ]
    matching.sort(key=lambda s: (distance_m(near, s.point), s.id))
    found: list[Stop] = []
    for s in matching:
        if any(
            o.name.casefold() == s.name.casefold()
            and distance_m(o.point, s.point) <= DUPLICATE_RADIUS_M
            for o in found
        ):
            continue
        found.append(s)
        if len(found) >= limit:
            break
    return [
        PlaceSuggestion(
            id=f"stop-{s.id}",
            title=s.name,
            subtitle="Остановка",
            kind=PlaceKind.STOP,
            point=s.point,
        )
        for s in found
    ]
