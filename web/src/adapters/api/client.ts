// Клиент API GoPoint. Сайт ходит на свой же адрес (/api/v1): адрес сервера
// в клиенте не зашит, поэтому один и тот же код работает на Mac и на сервере.
// Каждый ответ проверяется схемой zod: повреждённые данные не ломают интерфейс.
import { z } from 'zod';
import { firstRide, type Journey, type JourneyStep, type WalkStep } from '../../domain/journey';
import type {
  LatLon,
  LineDetails,
  LinesList,
  Meta as DomainMeta,
  PlaceSuggestion,
  StopArrivals,
  Vehicle as DomainVehicle,
  VehicleDetails,
} from '../../domain/types';
import { ApiError, type LiveApi } from '../../ports/LiveApi';
import type { PlaceSearch } from '../../ports/PlaceSearch';
import type { components } from './schema';

const API_BASE = '/api/v1';
// На слабом интернете не ждём бесконечно.
const TIMEOUT_MS = 15_000;
// Первый расчёт маршрута, остановки или карточки машины после запуска сервера
// идёт до ~25 с (грузятся линии всех маршрутов).
const ROUTE_TIMEOUT_MS = 45_000;

type Schemas = components['schemas'];

const latLon = z.object({ lat: z.number().min(-90).max(90), lon: z.number().min(-180).max(180) });
const accessibility = z.enum(['yes', 'no', 'unknown']);
const transportType = z.enum(['bus', 'trolleybus', 'tram', 'minibus']);
const direction = z.enum(['A', 'B']);

export const metaSchema = z.object({
  appName: z.string(),
  version: z.string(),
  cityBounds: z.object({ southWest: latLon, northEast: latLon }),
  refreshIntervalS: z.number().int().positive(),
  lowFloorOnlyDefault: z.boolean(),
  staleSeconds: z.number().int(),
}) satisfies z.ZodType<Schemas['Meta']>;

const vehicleSchema = z.object({
  id: z.string(),
  lineId: z.string(),
  type: transportType,
  number: z.string(),
  direction,
  point: latLon,
  azimuth: z.number().nullable().default(null),
  speedKmh: z.number().nullable().default(null),
  lowFloor: accessibility,
  positionObservedAt: z.string(),
});

const lineSchema = z.object({
  id: z.string(),
  type: transportType,
  number: z.string(),
  title: z.string(),
  ring: z.boolean().default(false),
});

const stopSchema = z.object({ id: z.string(), name: z.string(), point: latLon });

const diagnostics = z.object({ fetchedAt: z.string(), complete: z.boolean() });

const vehiclesSchema = z.object({
  vehicles: z.array(vehicleSchema),
  diagnostics,
}) satisfies z.ZodType<Schemas['VehiclesResponse']>;

const linesSchema = z.object({
  lines: z.array(z.object({ line: lineSchema, vehiclesOnLine: z.number().int().min(0) })),
  diagnostics,
}) satisfies z.ZodType<Schemas['LinesResponse']>;

const lineDetailsSchema = z.object({
  line: lineSchema,
  directions: z.array(
    z.object({
      direction,
      stops: z.array(stopSchema),
      path: z.array(latLon),
      vehicles: z.array(
        z.object({ vehicle: vehicleSchema, nextStopOrder: z.number().int().nullable() }),
      ),
    }),
  ),
  diagnostics,
}) satisfies z.ZodType<Schemas['LineDetails']>;

// Служебное: как посчитано время. Интерфейс его не показывает.
const etaDiagnostics = z.object({
  method: z.enum(['planned', 'distance']),
  positionObservedAt: z.string(),
});

const arrivalsSchema = z.object({
  stop: stopSchema,
  arrivals: z.array(
    z.object({
      vehicle: vehicleSchema,
      toward: z.string().nullable().default(null),
      stopsAway: z.number().int().min(0),
      arriveAt: z.string(),
      diagnostics: etaDiagnostics,
    }),
  ),
  diagnostics,
}) satisfies z.ZodType<Schemas['ArrivalsResponse']>;

const vehicleDetailsSchema = z.object({
  vehicle: vehicleSchema,
  toward: z.string().nullable().default(null),
  nextStops: z.array(
    z.object({ stop: stopSchema, arriveAt: z.string(), diagnostics: etaDiagnostics }),
  ),
  diagnostics,
}) satisfies z.ZodType<Schemas['VehicleDetails']>;

const placeSchema = z.object({
  id: z.string(),
  title: z.string().min(1),
  subtitle: z.string().nullable().default(null),
  kind: z.enum(['address', 'street', 'stop', 'place', 'area']),
  point: latLon,
});

const searchSchema = z.object({
  places: z.array(placeSchema),
}) satisfies z.ZodType<Schemas['SearchResponse']>;

const reverseSchema = z.object({
  place: placeSchema.nullable(),
}) satisfies z.ZodType<Schemas['ReverseResponse']>;

const walkLegSchema = z.object({
  kind: z.literal('walk'),
  origin: z.object({ name: z.string().nullable().default(null), point: latLon }),
  destination: z.object({ name: z.string().nullable().default(null), point: latLon }),
  distanceM: z.number().int().min(0),
  durationS: z.number().int().min(0),
  geometry: z.array(latLon).default([]),
  hasStairs: z.boolean().default(false),
});

const transitLegSchema = z.object({
  kind: z.literal('transit'),
  vehicleId: z.string(),
  line: lineSchema,
  lowFloor: accessibility,
  boardStop: stopSchema,
  alightStop: stopSchema,
  waitS: z.number().int().min(0),
  stopsCount: z.number().int().min(1),
  stopsAway: z.number().int().min(0),
  toward: z.string().nullable().default(null),
  departAt: z.string(),
  arriveAt: z.string(),
  geometry: z.array(latLon).default([]),
});

const journeySchema = z.object({
  legs: z.array(z.discriminatedUnion('kind', [walkLegSchema, transitLegSchema])).min(1),
  departAt: z.string(),
  arriveAt: z.string(),
  durationS: z.number().int().min(0),
  transfers: z.number().int().min(0),
  lowFloorOnly: z.boolean(),
  labels: z.array(z.enum(['fastest', 'fewest_transfers', 'least_walking'])).default([]),
});

const routeSchema = z.object({
  journeys: z.array(journeySchema).max(3),
  status: z.enum(['ok', 'no_transit']),
  message: z.string().nullable().optional(),
  walk: walkLegSchema.nullable().default(null),
  diagnostics,
});

const routeCheckSchema = z.object({
  status: z.enum(['ok', 'stopped', 'late', 'gone']),
  stoppedForS: z.number().int().nullable().default(null),
  current: journeySchema.nullable(),
  alternative: journeySchema.nullable(),
  gainS: z.number().int().nullable().optional(),
  diagnostics,
});

const apiErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  details: z.record(z.string(), z.unknown()).nullable().optional(),
});

const BAD_RESPONSE = 'Сервер прислал непонятный ответ. Попробуйте позже.';
const OFFLINE = 'Нет подключения к интернету.';
const TIMEOUT = 'Сервер долго не отвечает. Попробуйте ещё раз.';

function withTimeout(
  signal: AbortSignal | undefined,
  timeoutMs: number,
): {
  signal: AbortSignal;
  timedOut: () => boolean;
  done: () => void;
} {
  const controller = new AbortController();
  let expired = false;
  const timer = setTimeout(() => {
    expired = true;
    controller.abort();
  }, timeoutMs);
  const forward = () => {
    controller.abort();
  };
  signal?.addEventListener('abort', forward, { once: true });
  if (signal?.aborted) controller.abort();
  return {
    signal: controller.signal,
    timedOut: () => expired,
    done: () => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', forward);
    },
  };
}

export function getJson<T>(
  path: string,
  schema: z.ZodType<T>,
  signal?: AbortSignal,
  timeoutMs: number = TIMEOUT_MS,
): Promise<T> {
  return requestJson(path, schema, signal, { method: 'GET', timeoutMs });
}

async function requestJson<T>(
  path: string,
  schema: z.ZodType<T>,
  signal: AbortSignal | undefined,
  init: { method?: string; body?: unknown; timeoutMs?: number } = {},
): Promise<T> {
  const request = withTimeout(signal, init.timeoutMs ?? TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      signal: request.signal,
      ...(init.body === undefined
        ? {}
        : {
            method: init.method ?? 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(init.body),
          }),
    });
  } catch (error) {
    request.done();
    if (request.timedOut()) throw new ApiError(0, 'TIMEOUT', TIMEOUT);
    // Отмену устаревшего запроса пробрасываем как есть, остальное считаем отсутствием сети.
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'NETWORK', OFFLINE);
  }
  const body: unknown = await response.json().catch(() => null);
  request.done();
  if (!response.ok) {
    const parsed = apiErrorSchema.safeParse(body);
    if (parsed.success) throw new ApiError(response.status, parsed.data.code, parsed.data.message);
    throw new ApiError(response.status, 'BAD_RESPONSE', BAD_RESPONSE);
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) throw new ApiError(response.status, 'BAD_RESPONSE', BAD_RESPONSE);
  return parsed.data;
}

function toVehicle(v: z.infer<typeof vehicleSchema>): DomainVehicle {
  // Служебное время отметки (positionObservedAt) сайту не нужно:
  // устаревшие машины сервер уже отбросил.
  return {
    id: v.id,
    lineId: v.lineId,
    type: v.type,
    number: v.number,
    direction: v.direction,
    point: v.point,
    azimuth: v.azimuth,
    speedKmh: v.speedKmh,
    lowFloor: v.lowFloor,
  };
}

type JourneyBody = z.infer<typeof journeySchema>;

function toWalkStep(leg: z.infer<typeof walkLegSchema>): WalkStep {
  return {
    kind: 'walk',
    fromName: leg.origin.name,
    toName: leg.destination.name,
    distanceM: leg.distanceM,
    durationS: leg.durationS,
    geometry: leg.geometry,
    hasStairs: leg.hasStairs,
  };
}

function toJourney(j: JourneyBody): Journey {
  // Служебные поля (способ расчёта, время снимка) сайту не нужны и не показываются.
  const steps: JourneyStep[] = j.legs.map((leg) =>
    leg.kind === 'walk'
      ? toWalkStep(leg)
      : {
          kind: 'ride',
          vehicleId: leg.vehicleId,
          line: leg.line,
          lowFloor: leg.lowFloor,
          boardStop: leg.boardStop,
          alightStop: leg.alightStop,
          waitS: leg.waitS,
          stopsCount: leg.stopsCount,
          stopsAway: leg.stopsAway,
          toward: leg.toward,
          departAt: leg.departAt,
          arriveAt: leg.arriveAt,
          geometry: leg.geometry,
        },
  );
  return {
    steps,
    departAt: j.departAt,
    arriveAt: j.arriveAt,
    durationS: j.durationS,
    transfers: j.transfers,
    lowFloorOnly: j.lowFloorOnly,
    labels: j.labels,
  };
}

const point = (p: LatLon) => ({ lat: p.lat, lon: p.lon });

export function fetchMeta(signal?: AbortSignal): Promise<DomainMeta> {
  return getJson('/meta', metaSchema, signal);
}

const routeApi: Pick<LiveApi, 'planRoute' | 'checkRoute'> = {
  async planRoute(points, lowFloorOnly, signal) {
    // Координаты только в теле запроса к своему серверу (не в адресе); сервер их не пишет.
    const body = await requestJson('/route', routeSchema, signal, {
      body: {
        origin: point(points.origin),
        destination: point(points.destination),
        lowFloorOnly,
      },
      timeoutMs: ROUTE_TIMEOUT_MS,
    });
    return {
      status: body.status,
      journeys: body.journeys.map(toJourney),
      walk: body.walk ? toWalkStep(body.walk) : null,
    };
  },

  async checkRoute(points, lowFloorOnly, journey, plannedArriveAt, signal) {
    const ride = firstRide(journey);
    if (!ride) throw new ApiError(0, 'BAD_REQUEST', BAD_RESPONSE);
    const body = await requestJson('/route/check', routeCheckSchema, signal, {
      body: {
        origin: point(points.origin),
        destination: point(points.destination),
        lowFloorOnly,
        vehicleId: ride.vehicleId,
        plannedArriveAt,
      },
      timeoutMs: ROUTE_TIMEOUT_MS,
    });
    return {
      status: body.status,
      stoppedForS: body.stoppedForS,
      current: body.current ? toJourney(body.current) : null,
      alternative: body.alternative ? toJourney(body.alternative) : null,
    };
  },
};

export const httpLiveApi: LiveApi = {
  getMeta: fetchMeta,
  ...routeApi,

  async getVehicles(lowFloorOnly, signal) {
    const query = new URLSearchParams({ lowFloorOnly: String(lowFloorOnly) });
    const body = await getJson(`/live/vehicles?${query.toString()}`, vehiclesSchema, signal);
    return body.vehicles.map(toVehicle);
  },

  async getLines(lowFloorOnly, signal): Promise<LinesList> {
    const query = new URLSearchParams({ lowFloorOnly: String(lowFloorOnly) });
    const body = await getJson(`/live/routes?${query.toString()}`, linesSchema, signal);
    return { lines: body.lines, live: true, snapshotAt: body.diagnostics.fetchedAt };
  },

  async getLine(lineId, lowFloorOnly, signal): Promise<LineDetails> {
    const query = new URLSearchParams({ lowFloorOnly: String(lowFloorOnly) });
    const path = `/live/routes/${encodeURIComponent(lineId)}?${query.toString()}`;
    const body = await getJson(path, lineDetailsSchema, signal);
    return {
      line: body.line,
      live: true,
      snapshotAt: body.diagnostics.fetchedAt,
      directions: body.directions.map((d) => ({
        ...d,
        vehicles: d.vehicles.map((item) => ({
          vehicle: toVehicle(item.vehicle),
          nextStopOrder: item.nextStopOrder,
        })),
      })),
    };
  },

  async getStopArrivals(stopId, lowFloorOnly, signal): Promise<StopArrivals> {
    const query = new URLSearchParams({ lowFloorOnly: String(lowFloorOnly) });
    const path = `/live/stops/${encodeURIComponent(stopId)}/arrivals?${query.toString()}`;
    const body = await getJson(path, arrivalsSchema, signal, ROUTE_TIMEOUT_MS);
    return {
      stop: body.stop,
      arrivals: body.arrivals.map((a) => ({
        vehicle: toVehicle(a.vehicle),
        toward: a.toward,
        stopsAway: a.stopsAway,
        arriveAt: a.arriveAt,
      })),
    };
  },

  async getVehicleDetails(vehicleId, signal): Promise<VehicleDetails> {
    const path = `/live/vehicles/${encodeURIComponent(vehicleId)}`;
    const body = await getJson(path, vehicleDetailsSchema, signal, ROUTE_TIMEOUT_MS);
    return {
      vehicle: toVehicle(body.vehicle),
      toward: body.toward,
      nextStops: body.nextStops.map((s) => ({ stop: s.stop, arriveAt: s.arriveAt })),
    };
  },
};

export const httpPlaceSearch: PlaceSearch = {
  async search(query, signal): Promise<PlaceSuggestion[]> {
    const params = new URLSearchParams({ q: query });
    const body = await getJson(`/search?${params.toString()}`, searchSchema, signal);
    return body.places;
  },

  async reverse(point: LatLon, signal): Promise<PlaceSuggestion | null> {
    // Координаты только в запросе к своему серверу; сервер их не записывает.
    const params = new URLSearchParams({ lat: point.lat.toFixed(6), lon: point.lon.toFixed(6) });
    const body = await getJson(`/search/reverse?${params.toString()}`, reverseSchema, signal);
    return body.place;
  },
};

export { ApiError };
