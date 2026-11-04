// Клиент API GoPoint. Сайт ходит на свой же адрес (/api/v1): адрес сервера
// в клиенте не зашит, поэтому один и тот же код работает на Mac и на сервере.
// Каждый ответ проверяется схемой zod: повреждённые данные не ломают интерфейс.
import { z } from 'zod';
import type { components } from './schema';

const API_BASE = '/api/v1';

export type Meta = components['schemas']['Meta'];
export type ApiErrorBody = components['schemas']['ApiError'];

const latLon = z.object({ lat: z.number().min(-90).max(90), lon: z.number().min(-180).max(180) });

export const metaSchema = z.object({
  appName: z.string(),
  version: z.string(),
  cityBounds: z.object({ southWest: latLon, northEast: latLon }),
  refreshIntervalS: z.number().int().positive(),
  lowFloorOnlyDefault: z.boolean(),
  staleSeconds: z.number().int(),
}) satisfies z.ZodType<Meta>;

const apiErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  details: z.record(z.string(), z.unknown()).nullable().optional(),
});

/** Ошибка, которую можно показать человеку: message всегда по-русски. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

const BAD_RESPONSE = 'Сервер прислал непонятный ответ. Попробуйте позже.';
const OFFLINE = 'Нет подключения к интернету.';

export async function getJson<T>(
  path: string,
  schema: z.ZodType<T>,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, signal ? { signal } : {});
  } catch (error) {
    // Отмену устаревшего запроса пробрасываем как есть, остальное считаем отсутствием сети.
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'NETWORK', OFFLINE);
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const parsed = apiErrorSchema.safeParse(body);
    if (parsed.success) throw new ApiError(response.status, parsed.data.code, parsed.data.message);
    throw new ApiError(response.status, 'BAD_RESPONSE', BAD_RESPONSE);
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) throw new ApiError(response.status, 'BAD_RESPONSE', BAD_RESPONSE);
  return parsed.data;
}

export function fetchMeta(signal?: AbortSignal): Promise<Meta> {
  return getJson('/meta', metaSchema, signal);
}
