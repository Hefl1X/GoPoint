// Поиск адресов и адрес точки на карте через TanStack Query.
// Устаревшие запросы отменяются: при смене текста старый запрос остаётся без
// подписчиков, и TanStack Query прерывает его через signal.
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { isSearchable, normalizeQuery, SEARCH_DEBOUNCE_MS } from '../domain/places';
import type { LatLon, PlaceSuggestion } from '../domain/types';
import { useServices } from './services';

/** Значение, которое меняется только после паузы delayMs без изменений. */
export function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(value);
    }, delayMs);
    return () => {
      clearTimeout(timer);
    };
  }, [value, delayMs]);
  return debounced;
}

export interface PlaceSearchState {
  readonly query: UseQueryResult<readonly PlaceSuggestion[]>;
  /** Ещё ждём паузу после ввода или ответ сервера. */
  readonly pending: boolean;
  readonly searchable: boolean;
}

export function usePlaceSearch(text: string): PlaceSearchState {
  const { places } = useServices();
  const normalized = normalizeQuery(text);
  const debounced = useDebounced(normalized, SEARCH_DEBOUNCE_MS);
  const searchable = isSearchable(debounced);
  const query = useQuery({
    queryKey: ['search', debounced.toLowerCase()],
    queryFn: ({ signal }) => places.search(debounced, signal),
    enabled: searchable,
    staleTime: 10 * 60_000,
    retry: 0,
  });
  const waiting = isSearchable(normalized) && normalized !== debounced;
  return { query, pending: waiting || (searchable && query.isFetching), searchable };
}

/** Ключ точки с точностью ~10 м: мелкие сдвиги карты не дают новых запросов. */
function pointKey(point: LatLon): string {
  return `${point.lat.toFixed(4)},${point.lon.toFixed(4)}`;
}

export function useReversePlace(point: LatLon | null): UseQueryResult<PlaceSuggestion | null> {
  const { places } = useServices();
  // Карта может ещё двигаться: ждём паузу, как при вводе.
  const debounced = useDebounced(point, SEARCH_DEBOUNCE_MS);
  return useQuery({
    queryKey: ['reverse', debounced ? pointKey(debounced) : null],
    queryFn: ({ signal }) => (debounced ? places.reverse(debounced, signal) : null),
    enabled: debounced !== null,
    staleTime: 10 * 60_000,
    retry: 0,
  });
}
