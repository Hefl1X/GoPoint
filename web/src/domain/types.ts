// Типы предметной области сайта. Без сети, без React, без адаптеров.
// Координаты всегда объект { lat, lon }, не массив.

export interface LatLon {
  readonly lat: number;
  readonly lon: number;
}

export type Accessibility = 'yes' | 'no' | 'unknown';

/** Только `yes` считается низкопольной машиной: `unknown` никогда не показывается как `yes`. */
export function isLowFloor(value: Accessibility): boolean {
  return value === 'yes';
}
