// Плавный переход машины между двумя присланными положениями.
// Честность: показываем только то, что прислал сервер. Машина плавно переезжает от прежнего
// положения к новому и не едет дальше присланной точки (никаких догадок «куда она поедет»).
import type { LatLon } from './types';

/** Сколько длится переезд к новому положению. */
export const MOTION_MS = 1500;
/** Дальше этого (метров) считаем сменой данных, а не движением: переезд не растягиваем. */
export const MAX_SMOOTH_JUMP_M = 1500;

const M_PER_DEG_LAT = 111_000;

function approxDistanceM(a: LatLon, b: LatLon): number {
  const dLat = (b.lat - a.lat) * M_PER_DEG_LAT;
  const dLon = (b.lon - a.lon) * M_PER_DEG_LAT * Math.cos((a.lat * Math.PI) / 180);
  return Math.hypot(dLat, dLon);
}

/** Доля пути от 0 до 1 по прошедшему времени (плавный старт и остановка). */
export function motionProgress(elapsedMs: number): number {
  const t = Math.min(1, Math.max(0, elapsedMs / MOTION_MS));
  return t === 1 ? 1 : t * t * (3 - 2 * t);
}

/** Точка на пути от `from` к `to`; доля t ограничена отрезком [0, 1]. */
export function blendPoint(from: LatLon | null, to: LatLon, t: number): LatLon {
  if (from === null || approxDistanceM(from, to) > MAX_SMOOTH_JUMP_M) return to;
  const k = Math.min(1, Math.max(0, t));
  if (k === 1) return to;
  if (k === 0) return from;
  return { lat: from.lat + (to.lat - from.lat) * k, lon: from.lon + (to.lon - from.lon) * k };
}
