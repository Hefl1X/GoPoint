// Клиент API GoPoint. Сайт ходит на свой же адрес (/api/v1): адрес сервера
// в клиенте не зашит, поэтому один и тот же код работает на Mac и на сервере.
// Каждый ответ проверяется схемой zod: повреждённые данные не ломают интерфейс.
import { z } from 'zod';
import type {
  LineDetails,
  LineSummary,
  Meta as DomainMeta,
  Vehicle as DomainVehicle,
} from '../../domain/types';
import { ApiError, type LiveApi } from '../../ports/LiveApi';
import type { components } from './schema';

const API_BASE = '/api/v1';
// На слабом интернете не ждём бесконечно.
const TIMEOUT_MS = 15_000;

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

const apiErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  details: z.record(z.string(), z.unknown()).nullable().optional(),
});

const BAD_RESPONSE = 'Сервер прислал непонятный ответ. Попробуйте позже.';
const OFFLINE = 'Нет подключения к интернету.';
const TIMEOUT = 'Сервер долго не отвечает. Попробуйте ещё раз.';

function withTimeout(signal: AbortSignal | undefined): {
  signal: AbortSignal;
  timedOut: () => boolean;
  done: () => void;
} {
  const controller = new AbortController();
  let expired = false;
  const timer = setTimeout(() => {
    expired = true;
    controller.abort();
  }, TIMEOUT_MS);
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

export async function getJson<T>(
  path: string,
  schema: z.ZodType<T>,
  signal?: AbortSignal,
): Promise<T> {
  const request = withTimeout(signal);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { signal: request.signal });
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

export function fetchMeta(signal?: AbortSignal): Promise<DomainMeta> {
  return getJson('/meta', metaSchema, signal);
}

export const httpLiveApi: LiveApi = {
  getMeta: fetchMeta,

  async getVehicles(lowFloorOnly, signal) {
    const query = new URLSearchParams({ lowFloorOnly: String(lowFloorOnly) });
    const body = await getJson(`/live/vehicles?${query.toString()}`, vehiclesSchema, signal);
    return body.vehicles.map(toVehicle);
  },

  async getLines(lowFloorOnly, signal): Promise<LineSummary[]> {
    const query = new URLSearchParams({ lowFloorOnly: String(lowFloorOnly) });
    const body = await getJson(`/live/routes?${query.toString()}`, linesSchema, signal);
    return body.lines;
  },

  async getLine(lineId, lowFloorOnly, signal): Promise<LineDetails> {
    const query = new URLSearchParams({ lowFloorOnly: String(lowFloorOnly) });
    const path = `/live/routes/${encodeURIComponent(lineId)}?${query.toString()}`;
    const body = await getJson(path, lineDetailsSchema, signal);
    return {
      line: body.line,
      directions: body.directions.map((d) => ({
        ...d,
        vehicles: d.vehicles.map((item) => ({
          vehicle: toVehicle(item.vehicle),
          nextStopOrder: item.nextStopOrder,
        })),
      })),
    };
  },
};

export { ApiError };
