// Порт поиска адресов. Реализация: adapters/api (наш сервер, который спрашивает Photon).
import type { LatLon, PlaceSuggestion } from '../domain/types';

export interface PlaceSearch {
  /** Подсказки по тексту (от 3 букв) в пределах Новосибирска. */
  search(query: string, signal?: AbortSignal): Promise<readonly PlaceSuggestion[]>;
  /** Адрес у точки на карте; null, если рядом ничего не нашлось. */
  reverse(point: LatLon, signal?: AbortSignal): Promise<PlaceSuggestion | null>;
}
