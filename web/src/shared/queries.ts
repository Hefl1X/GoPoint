// Данные с сервера через TanStack Query. Положения машин обновляются раз в
// refreshIntervalS (30 с); когда вкладка скрыта, обновление останавливается
// (refetchIntervalInBackground: false). Устаревшие данные не показываются.
import { onlineManager, useQuery, type UseQueryResult } from '@tanstack/react-query';
import { useSyncExternalStore } from 'react';
import type { Journey, RouteCheck, RoutePlan, RoutePoints } from '../domain/journey';
import type {
  LineDetails,
  LinesList,
  Meta,
  StopArrivals,
  Vehicle,
  VehicleDetails,
} from '../domain/types';
import { hideOldLine, hideOldLines } from '../domain/transport';
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
    // Без сети ответ может прийти из сохранённых (service worker).
    networkMode: 'offlineFirst',
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

/**
 * Справочники (маршруты, остановки) работают и без сети: запрос всё равно уходит,
 * service worker отвечает сохранённым. Машины из такого ответа скрываются (hideOld*).
 */
export function useLines(lowFloorOnly: boolean): LiveQuery<LinesList> {
  const { api } = useServices();
  const { refreshMs, staleMs } = useLiveTiming();
  const query = useQuery({
    queryKey: ['lines', lowFloorOnly],
    queryFn: async ({ signal }) =>
      hideOldLines(await api.getLines(lowFloorOnly, signal), Date.now(), staleMs),
    ...liveOptions(refreshMs),
    networkMode: 'offlineFirst',
  });
  return { query, data: freshData(query, staleMs) };
}

export function useLine(lineId: string | null, lowFloorOnly: boolean): LiveQuery<LineDetails> {
  const { api } = useServices();
  const { refreshMs, staleMs } = useLiveTiming();
  const query = useQuery({
    queryKey: ['line', lineId, lowFloorOnly],
    queryFn: async ({ signal }) =>
      hideOldLine(await api.getLine(lineId ?? '', lowFloorOnly, signal), Date.now(), staleMs),
    enabled: lineId !== null,
    ...liveOptions(refreshMs),
    networkMode: 'offlineFirst',
  });
  return { query, data: freshData(query, staleMs) };
}

export function useStopArrivals(stopId: string, lowFloorOnly: boolean): LiveQuery<StopArrivals> {
  const { api } = useServices();
  const { refreshMs, staleMs } = useLiveTiming();
  const query = useQuery({
    queryKey: ['stop', stopId, lowFloorOnly],
    queryFn: ({ signal }) => api.getStopArrivals(stopId, lowFloorOnly, signal),
    ...liveOptions(refreshMs),
  });
  return { query, data: freshData(query, staleMs) };
}

export function useVehicleDetails(vehicleId: string | null): LiveQuery<VehicleDetails> {
  const { api } = useServices();
  const { refreshMs, staleMs } = useLiveTiming();
  const query = useQuery({
    queryKey: ['vehicle', vehicleId],
    queryFn: ({ signal }) => api.getVehicleDetails(vehicleId ?? '', signal),
    enabled: vehicleId !== null,
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

const pointKey = (p: RoutePoints) =>
  [p.origin.lat, p.origin.lon, p.destination.lat, p.destination.lon].map((n) => n.toFixed(6));

/**
 * Маршрут «сейчас». Сам не обновляется: построенный маршрут меняется только по решению
 * человека (пересчёт ниже). Новый расчёт при смене точек или настройки.
 */
export function useRoutePlan(
  points: RoutePoints | null,
  lowFloorOnly: boolean,
): UseQueryResult<RoutePlan> {
  const { api } = useServices();
  return useQuery({
    queryKey: ['route', points ? pointKey(points) : null, lowFloorOnly],
    queryFn: ({ signal }) => {
      if (!points) throw new Error('нет точек');
      return api.planRoute(points, lowFloorOnly, signal);
    },
    enabled: points !== null,
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

/** Проверка выбранного маршрута раз в 30 с, пока вкладка открыта. */
export function useRouteCheck(
  points: RoutePoints | null,
  lowFloorOnly: boolean,
  journey: Journey | null,
  plannedArriveAt: string | null,
): UseQueryResult<RouteCheck> {
  const { api } = useServices();
  const { refreshMs } = useLiveTiming();
  const vehicles = journey
    ? journey.steps.flatMap((s) => (s.kind === 'ride' ? [s.vehicleId] : []))
    : [];
  return useQuery({
    queryKey: [
      'route-check',
      points ? pointKey(points) : null,
      lowFloorOnly,
      vehicles.join('>'),
      plannedArriveAt,
    ],
    queryFn: ({ signal }) => {
      if (!points || !journey || !plannedArriveAt) throw new Error('нет маршрута');
      return api.checkRoute(points, lowFloorOnly, journey, plannedArriveAt, signal);
    },
    enabled: points !== null && journey !== null && plannedArriveAt !== null && vehicles.length > 0,
    refetchInterval: refreshMs,
    refetchIntervalInBackground: false,
    staleTime: refreshMs / 2,
    retry: false,
  });
}
