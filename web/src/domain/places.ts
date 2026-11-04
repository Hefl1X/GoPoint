// Правила поиска адресов и точек А/Б на сайте. Без сети и React.
import type { Endpoint, PlaceKind, TripPoint } from './types';

/** Поиск начинается с трёх букв (как на сервере). */
export const MIN_QUERY_LENGTH = 3;
/** Пауза после ввода, прежде чем искать. */
export const SEARCH_DEBOUNCE_MS = 300;

export function normalizeQuery(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}

export function isSearchable(text: string): boolean {
  return normalizeQuery(text).length >= MIN_QUERY_LENGTH;
}

/** Короткая подпись вида места в подсказке (текст, а не только значок). */
export const KIND_LABEL: Record<PlaceKind, string> = {
  address: 'адрес',
  street: 'улица',
  stop: 'ост.',
  place: 'место',
  area: 'район',
};

export const ENDPOINT_LETTER: Record<Endpoint, string> = { from: 'А', to: 'Б' };

/** Какую точку выбирать кнопкой «Выбрать на карте» на главном экране: сначала «Куда». */
export function nextEndpoint(from: TripPoint | null, to: TripPoint | null): Endpoint {
  if (to === null) return 'to';
  if (from === null) return 'from';
  return 'to';
}
