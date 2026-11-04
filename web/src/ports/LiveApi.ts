// Порт сервера GoPoint. Реализация: adapters/api.
import type { LineDetails, LineSummary, Meta, Vehicle } from '../domain/types';

export interface LiveApi {
  getMeta(signal?: AbortSignal): Promise<Meta>;
  getVehicles(lowFloorOnly: boolean, signal?: AbortSignal): Promise<readonly Vehicle[]>;
  getLines(lowFloorOnly: boolean, signal?: AbortSignal): Promise<readonly LineSummary[]>;
  getLine(lineId: string, lowFloorOnly: boolean, signal?: AbortSignal): Promise<LineDetails>;
}

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
