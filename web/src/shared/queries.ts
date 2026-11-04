// Данные с сервера через TanStack Query. Положения машин обновляются раз в
// refreshIntervalS (30 с); когда вкладка скрыта, обновление останавливается
// (refetchIntervalInBackground: false). Устаревшие данные не показываются.
import { onlineManager, useQuery, type UseQueryResult } from '@tanstack/react-query';
import { useSyncExternalStore } from 'react';
import type { LineDetails, LineSummary, Meta, Vehicle } from '../domain/types';
import { useServices } from './services';

const DEFAULT_REFRESH_S = 30;
const DEFAULT_STALE_S = 300;

export function useMeta(): UseQueryResult<Meta> {
  const { api } = useServices();
  return useQuery({
    queryKey: ['meta'],
    queryFn: ({ signal }) => api.getMeta(signal),
    staleTime: Infinity,
    retry: 2,
  });
}

function useLiveTiming() {
  const meta = useMeta().data;
  return {
    refreshMs: (meta?.refreshIntervalS ?? DEFAULT_REFRESH_S) * 1000,
    staleMs: (meta?.staleSeconds ?? DEFAULT_STALE_S) * 1000,
  };
}

const liveOptions = (refreshMs: number) => ({
  refetchInterval: refreshMs,
  refetchIntervalInBackground: false,
  staleTime: refreshMs / 2,
  retry: 1,
});

/**
 * Последний успешный ответ старше порога свежести считается отсутствием данных:
 * машины, которые могли уехать, не показываются (например, после долгой потери сети).
 */
export function freshData<T>(
  query: UseQueryResult<T>,
  staleMs: number,
  now = Date.now(),
): T | undefined {
  if (query.data === undefined) return undefined;
  return now - query.dataUpdatedAt > staleMs ? undefined : query.data;
}

export interface LiveQuery<T> {
  readonly query: UseQueryResult<T>;
  readonly data: T | undefined;
}

export function useVehicles(lowFloorOnly: boolean): LiveQuery<readonly Vehicle[]> {
  const { api } = useServices();
  const { refreshMs, staleMs } = useLiveTiming();
  const query = useQuery({
    queryKey: ['vehicles', lowFloorOnly],
    queryFn: ({ signal }) => api.getVehicles(lowFloorOnly, signal),
    ...liveOptions(refreshMs),
  });
  return { query, data: freshData(query, staleMs) };
}

export function useLines(lowFloorOnly: boolean): LiveQuery<readonly LineSummary[]> {
  const { api } = useServices();
  const { refreshMs, staleMs } = useLiveTiming();
  const query = useQuery({
    queryKey: ['lines', lowFloorOnly],
    queryFn: ({ signal }) => api.getLines(lowFloorOnly, signal),
    ...liveOptions(refreshMs),
  });
  return { query, data: freshData(query, staleMs) };
}

export function useLine(lineId: string | null, lowFloorOnly: boolean): LiveQuery<LineDetails> {
  const { api } = useServices();
  const { refreshMs, staleMs } = useLiveTiming();
  const query = useQuery({
    queryKey: ['line', lineId, lowFloorOnly],
    queryFn: ({ signal }) => api.getLine(lineId ?? '', lowFloorOnly, signal),
    enabled: lineId !== null,
    ...liveOptions(refreshMs),
  });
  return { query, data: freshData(query, staleMs) };
}

export function useOnline(): boolean {
  return useSyncExternalStore(
    (onChange) => onlineManager.subscribe(onChange),
    () => onlineManager.isOnline(),
  );
}
