// Правила показа транспорта: названия видов, цвета, пометки, склонения.
import type { Accessibility, LineDirection, LineSummary, TransportType } from './types';

export const TRANSPORT_TYPES: readonly TransportType[] = ['bus', 'trolleybus', 'tram', 'minibus'];

const TYPE_NAME: Record<TransportType, string> = {
  bus: 'Автобус',
  trolleybus: 'Троллейбус',
  tram: 'Трамвай',
  minibus: 'Маршрутка',
};

const TYPE_PLURAL: Record<TransportType, string> = {
  bus: 'Автобусы',
  trolleybus: 'Троллейбусы',
  tram: 'Трамваи',
  minibus: 'Маршрутки',
};

/**
 * Цвет «таблетки» маршрута по виду транспорта (у ЦУГАЭТ своих цветов нет).
 * На всех белая цифра с контрастом от 4.5:1 (проверяется тестом).
 */
export const TYPE_COLOR: Record<TransportType, string> = {
  bus: '#1d4ed8',
  trolleybus: '#8a3a0f',
  tram: '#b4236b',
  minibus: '#6d28d9',
};

/** Цвет машин не из выбранного маршрута. */
export const MUTED_COLOR = '#5b6b67';

export function typeName(type: TransportType): string {
  return TYPE_NAME[type];
}

export function typePlural(type: TransportType): string {
  return TYPE_PLURAL[type];
}

/** «Автобус 8», «Трамвай 13». */
export function lineName(type: TransportType, number: string): string {
  return `${TYPE_NAME[type]} ${number}`;
}

/** Пометка о низком поле: не только цвет, всегда ещё и текст. */
export function lowFloorLabel(value: Accessibility): string {
  switch (value) {
    case 'yes':
      return 'низкий пол';
    case 'no':
      return 'не низкий пол';
    case 'unknown':
      return 'низкий пол не указан';
  }
}

/** Склонение по числу: plural(1, 'машина', 'машины', 'машин'). */
export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

/** «На линии сейчас: 23 низкопольные машины» или «…: 5 машин». */
export function onLineText(count: number, lowFloorOnly: boolean): string {
  const noun = plural(count, 'машина', 'машины', 'машин');
  if (!lowFloorOnly) return `На линии сейчас: ${String(count)} ${noun}`;
  const adjective = plural(count, 'низкопольная', 'низкопольные', 'низкопольных');
  return `На линии сейчас: ${String(count)} ${adjective} ${noun}`;
}

export function vehiclesOnLineText(count: number): string {
  return `на линии: ${String(count)} ${plural(count, 'машина', 'машины', 'машин')}`;
}

/** Список «Транспорт сейчас»: фильтр по виду и номеру, при lowFloorOnly только где есть машины. */
export function filterLines(
  lines: readonly LineSummary[],
  options: { type: TransportType | 'all'; query: string; lowFloorOnly: boolean },
): LineSummary[] {
  const query = options.query.trim().toLowerCase();
  return lines.filter(
    (item) =>
      (options.type === 'all' || item.line.type === options.type) &&
      (query === '' || item.line.number.toLowerCase().startsWith(query)) &&
      (!options.lowFloorOnly || item.vehiclesOnLine > 0),
  );
}

/** Куда едет направление: последняя остановка на линии. */
export function towardStop(direction: LineDirection): string | null {
  return direction.stops.at(-1)?.name ?? null;
}

// Контраст по WCAG 2.x.
function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const value = Number.parseInt(hex.slice(1), 16);
  const r = (value >> 16) & 255;
  const g = (value >> 8) & 255;
  const b = value & 255;
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(foreground: string, background: string): number {
  const [hi, lo] = [luminance(foreground), luminance(background)].sort((a, b) => b - a) as [
    number,
    number,
  ];
  return (hi + 0.05) / (lo + 0.05);
}
