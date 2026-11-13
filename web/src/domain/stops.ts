// Остановки на карте: показываются только вблизи, чтобы карта оставалась чистой.
import type { MapViewport } from '../ports/MapView';
import type { Bounds } from './types';

/** С этого масштаба на карте видны остановки (улицы и дома различимы). */
export const MIN_STOPS_ZOOM = 15;

/** Область, для которой нужны остановки; null, если карта далеко или область неизвестна. */
export function stopsArea(view: MapViewport | null): Bounds | null {
  return view && view.zoom >= MIN_STOPS_ZOOM ? view.bounds : null;
}
