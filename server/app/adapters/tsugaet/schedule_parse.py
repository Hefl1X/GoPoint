"""Чистый разбор XML-справочников и HTML расписания grasp.php."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from xml.etree import ElementTree

from app.adapters.tsugaet.parse import TsugaetFormatError
from app.domain.schedule import (
    RouteSchedule,
    ScheduleDay,
    ScheduleDayKind,
    ScheduleRoute,
    ScheduleStop,
    StopSchedule,
)

_DAY_KINDS = {
    "ежедневно": ScheduleDayKind.DAILY,
    "будни": ScheduleDayKind.WEEKDAYS,
    "выходное": ScheduleDayKind.WEEKENDS,
}
_INTEGER = re.compile(r"[0-9]{1,2}")
_STOP_ID = re.compile(r"([0-9]+)\|([0-9]+)")
_PAGE_END = re.compile(r"</body>\s*</html>\s*\Z", re.IGNORECASE)
_HOURS = frozenset({"td_plan_h", "td_plan_n"})
_MINUTES = "td_plan_m"
_CHILDREN = {"table": {"tr"}, "tr": {"td"}, "td": {"span", "div"}}


class UnsupportedScheduleDayError(TsugaetFormatError):
    """Справочник валиден, но календарное значение типа дня пока неизвестно."""


def _xml_entries(xml: str, root_tag: str, entry_tag: str) -> tuple[tuple[str, str], ...]:
    # В справочниках нет DTD или объявлений сущностей.
    if "<!DOCTYPE" in xml:
        raise TsugaetFormatError(f"grasp {root_tag}: DTD не поддерживается")
    try:
        root = ElementTree.fromstring(xml)  # noqa: S314 — DTD отклоняется выше
    except ElementTree.ParseError as exc:
        raise TsugaetFormatError(f"grasp {root_tag}: повреждённый XML") from exc
    if root.tag != root_tag or (root.text or "").strip():
        raise TsugaetFormatError(f"grasp: ожидался список {root_tag}")

    entries: dict[str, str] = {}
    for entry in root:
        if (
            entry.tag != entry_tag
            or len(entry)
            or any(text and text.strip() for text in (entry.text, entry.tail))
        ):
            raise TsugaetFormatError(f"grasp {root_tag}: неверная запись {entry_tag}")
        source_id = entry.get("id", "").strip()
        title = " ".join(entry.get("title", "").split())
        if not source_id or not title or source_id in entries:
            raise TsugaetFormatError(f"grasp {root_tag}: отсутствующий или повторный id/title")
        entries[source_id] = title
    return tuple(entries.items())


def parse_schedule_day(xml: str, source_id: str) -> ScheduleDay:
    """Интерпретировать выбранный тип дня по заголовку, сохраняя исходный ID."""
    days = dict(_xml_entries(xml, "schedules", "schedule"))
    title = days.get(source_id)
    if title is None:
        raise TsugaetFormatError(f"grasp schedules: нет типа дня {source_id!r}")
    kind = _DAY_KINDS.get(title.casefold())
    if kind is None:
        raise UnsupportedScheduleDayError(f"grasp schedules: неизвестный тип дня {title!r}")
    return ScheduleDay(source_id, title, kind)


def parse_schedule_stops(xml: str) -> tuple[ScheduleStop, ...]:
    stops: list[ScheduleStop] = []
    for sequence, (source_id, name) in enumerate(_xml_entries(xml, "stops", "stop"), start=1):
        match = _STOP_ID.fullmatch(source_id)
        if match is None or match[2] != str(sequence):
            raise TsugaetFormatError(f"grasp stops: ожидалась остановка на позиции {sequence}")
        stops.append(ScheduleStop(match[1], sequence, name))
    return tuple(stops)


@dataclass
class _Cell:
    kind: str
    values: list[tuple[str, str]] = field(default_factory=list)


def _clock_number(text: str, upper: int) -> int:
    if _INTEGER.fullmatch(text) is None or int(text) >= upper:
        raise TsugaetFormatError("grasp HTML: неверный час или минута")
    return int(text)


def _hour(cell: _Cell) -> int:
    if cell.kind not in _HOURS or len(cell.values) != 1 or cell.values[0][0] != "span":
        raise TsugaetFormatError("grasp HTML: ожидалась ячейка часа")
    return _clock_number(cell.values[0][1], 24)


def _minutes(cell: _Cell, *, has_departures: bool) -> tuple[int, ...]:
    if cell.kind == _MINUTES:
        if not has_departures and cell.values == [("span", "")]:
            return ()
        if has_departures and cell.values and all(tag == "div" for tag, _ in cell.values):
            return tuple(_clock_number(value, 60) for _, value in cell.values)
    raise TsugaetFormatError("grasp HTML: минуты не соответствуют ячейке часа")


@dataclass(frozen=True)
class _StopTable:
    name: str
    first_hour: int
    departures: tuple[int, ...]


def _stop_table(name: str, rows: list[list[_Cell]]) -> _StopTable:
    if any(not row or len(row) % 2 for row in rows) or sum(map(len, rows)) != 48:
        raise TsugaetFormatError("grasp HTML: неполная таблица часов и минут")
    cells = [cell for row in rows for cell in row]
    first_hour = _hour(cells[0])
    departures: list[int] = []
    for offset, (hour_cell, minute_cell) in enumerate(zip(cells[::2], cells[1::2], strict=True)):
        service_hour = first_hour + offset
        if _hour(hour_cell) != service_hour % 24:
            raise TsugaetFormatError("grasp HTML: нарушен порядок часов")
        minutes = _minutes(minute_cell, has_departures=hour_cell.kind == "td_plan_h")
        departures.extend((service_hour * 60 + minute) * 60 for minute in minutes)
    return _StopTable(name, first_hour, tuple(departures))


class _ScheduleHtml(HTMLParser):
    """Строго проверяет разметку таблиц внутри страницы источника."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_StopTable] = []
        self._stack: list[str] = []
        self._name = ""
        self._text: list[str] = []
        self._rows: list[list[_Cell]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if self._stack:
            if tag not in _CHILDREN.get(self._stack[-1], ()):
                raise TsugaetFormatError(f"grasp HTML: неожиданный тег {tag} в расписании")
            self._stack.append(tag)
            if tag == "tr":
                self._rows.append([])
            elif tag == "td":
                self._rows[-1].append(_Cell(attributes.get("class") or ""))
        elif tag == "h2":
            if self._name:
                raise TsugaetFormatError("grasp HTML: заголовок остановки без таблицы")
            self._stack.append(tag)
        elif tag == "table" and attributes.get("class") == "tbl_plan_rasp":
            if not self._name:
                raise TsugaetFormatError("grasp HTML: таблица без заголовка остановки")
            self._stack.append(tag)

    def handle_data(self, data: str) -> None:
        if not self._stack:
            return
        if self._stack[-1] in {"h2", "span", "div"}:
            self._text.append(data)
        elif data.strip():
            raise TsugaetFormatError("grasp HTML: неожиданный текст в таблице")

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return
        if tag != self._stack.pop():
            raise TsugaetFormatError(f"grasp HTML: неожиданный закрывающий тег {tag}")
        if tag in {"h2", "span", "div"}:
            value = " ".join("".join(self._text).split())
            self._text.clear()
            if tag == "h2":
                prefix, _, name = value.partition(" ")
                if prefix.casefold() != "остановка" or not name:
                    raise TsugaetFormatError("grasp HTML: неверный заголовок остановки")
                self._name = name
            else:
                self._rows[-1][-1].values.append((tag, value))
        elif tag == "table":
            self.tables.append(_stop_table(self._name, self._rows))
            self._name = ""
            self._rows.clear()

    def close(self) -> None:
        super().close()
        if self._stack or self._name or not self.tables:
            raise TsugaetFormatError("grasp HTML: отсутствует полное расписание")


def parse_schedule_tables(html: str, stops: tuple[ScheduleStop, ...]) -> tuple[StopSchedule, ...]:
    """Читает полную или одиночную страницу и сверяет таблицы со справочником остановок."""
    if _PAGE_END.search(html) is None:
        raise TsugaetFormatError("grasp HTML: обрезанный или неверный ответ")
    parser = _ScheduleHtml()
    parser.feed(html)
    parser.close()
    if len(parser.tables) != len(stops):
        raise TsugaetFormatError("grasp HTML: число таблиц не совпало со справочником остановок")
    if len({table.first_hour for table in parser.tables}) != 1:
        raise TsugaetFormatError("grasp HTML: таблицы начинаются с разных часов")

    result: list[StopSchedule] = []
    for stop, table in zip(stops, parser.tables, strict=True):
        if table.name != stop.name:
            raise TsugaetFormatError(f"grasp HTML: название не совпало на позиции {stop.sequence}")
        result.append(StopSchedule(stop, table.departures))
    return tuple(result)


def parse_route_schedule(
    html: str, stops_xml: str, days_xml: str, *, route: ScheduleRoute, day_id: str
) -> RouteSchedule:
    day = parse_schedule_day(days_xml, day_id)
    return RouteSchedule(route, day, parse_schedule_tables(html, parse_schedule_stops(stops_xml)))
