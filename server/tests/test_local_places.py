"""Свои подсказки поиска: синонимы (НГУ, вокзал) и остановки ЦУГАЭТ (без сети)."""

from __future__ import annotations

from pathlib import Path

from app.domain.local_places import Alias, load_aliases, match_aliases, match_stops
from app.domain.models import LatLon, PlaceKind, PlaceSuggestion, Stop

CENTER = LatLon(lat=55.03, lon=82.92)
ALIASES_FILE = Path(__file__).parents[1] / "app" / "adapters" / "local_places" / "aliases_nsk.csv"


def alias(names: tuple[str, ...], title: str) -> Alias:
    return Alias(
        names=names,
        place=PlaceSuggestion(
            id=f"alias-{title}",
            title=title,
            kind=PlaceKind.PLACE,
            point=CENTER,
        ),
    )


def stop(sid: str, name: str, lat: float = 55.03, lon: float = 82.92) -> Stop:
    return Stop(id=sid, name=name, point=LatLon(lat=lat, lon=lon))


def test_alias_exact_match_ignores_case_yo_and_spaces() -> None:
    aliases = [alias(("нгу",), "НГУ")]
    assert [p.title for p in match_aliases("  НГУ ", aliases)] == ["НГУ"]


def test_alias_prefix_needs_four_letters() -> None:
    aliases = [alias(("вокзал",), "Главный")]
    assert match_aliases("вокз", aliases)
    assert match_aliases("вок", aliases) == []
    assert match_aliases("нгу", aliases) == []


def test_each_alias_once_even_if_several_names_match() -> None:
    aliases = [alias(("вокзал", "вокзал главный"), "Главный")]
    assert len(match_aliases("вокзал", aliases)) == 1


def test_real_file_covers_audit_cases() -> None:
    aliases = load_aliases(ALIASES_FILE)
    assert match_aliases("вокзал", aliases)[0].title == "Новосибирск-Главный"
    assert "университет" in match_aliases("НГУ", aliases)[0].title.lower()
    assert "№ 1" in match_aliases("больница 1", aliases)[0].title


def test_stops_match_by_word_prefixes_in_any_order() -> None:
    stops = [stop("1", "Площадь Маркса"), stop("2", "Цирк")]
    found = match_stops("маркса пл", stops, CENTER, limit=3)
    assert [p.title for p in found] == ["Площадь Маркса"]
    assert found[0].kind is PlaceKind.STOP
    assert found[0].id == "stop-1"


def test_stops_same_name_nearby_collapse_far_stay_and_nearest_first() -> None:
    stops = [
        stop("far", "Цирк", lat=55.10),
        stop("a", "Цирк", lat=55.0301),
        stop("b", "Цирк", lat=55.0302),  # напротив первой: одна подсказка
    ]
    found = match_stops("цирк", stops, CENTER, limit=3)
    assert [p.id for p in found] == ["stop-a", "stop-far"]


def test_stops_limit() -> None:
    stops = [stop(str(i), f"Школа {i}", lat=55.03 + i * 0.01) for i in range(6)]
    assert len(match_stops("школа", stops, CENTER, limit=2)) == 2
