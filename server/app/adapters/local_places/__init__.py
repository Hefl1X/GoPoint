"""Свои подсказки поиска: синонимы из файла `aliases_nsk.csv` и остановки ЦУГАЭТ.

Файл синонимов правится вручную (добавьте строку: имена через |, название, подпись,
вид, координаты). Остановки берутся из уже загруженных линий: новых запросов к ЦУГАЭТ нет.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.domain.local_places import Alias, load_aliases, match_aliases, match_stops
from app.domain.models import LatLon, PlaceSuggestion, Stop

ALIASES_FILE = Path(__file__).with_name("aliases_nsk.csv")
STOPS_IN_SUGGESTIONS = 2


class LocalPlacesProvider:
    def __init__(
        self, known_stops: Callable[[], list[Stop]], aliases: list[Alias] | None = None
    ) -> None:
        self._aliases = aliases if aliases is not None else load_aliases(ALIASES_FILE)
        self._known_stops = known_stops

    async def search(self, query: str, near: LatLon) -> list[PlaceSuggestion]:
        return [
            *match_aliases(query, self._aliases),
            *match_stops(query, self._known_stops(), near, limit=STOPS_IN_SUGGESTIONS),
        ]
