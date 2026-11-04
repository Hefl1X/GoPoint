// Типы предметной области сайта. Без сети, без React, без адаптеров.
// Координаты всегда объект { lat, lon }, не массив.

export interface LatLon {
  readonly lat: number;
  readonly lon: number;
}

export interface Bounds {
  readonly southWest: LatLon;
  readonly northEast: LatLon;
}

export type Accessibility = 'yes' | 'no' | 'unknown';
export type TransportType = 'bus' | 'trolleybus' | 'tram' | 'minibus';
export type Direction = 'A' | 'B';

/** Только `yes` считается низкопольной машиной: `unknown` никогда не показывается как `yes`. */
export function isLowFloor(value: Accessibility): boolean {
  return value === 'yes';
}

export interface Line {
  readonly id: string;
  readonly type: TransportType;
  readonly number: string;
  readonly title: string;
}

export interface Vehicle {
  readonly id: string;
  readonly lineId: string;
  readonly type: TransportType;
  readonly number: string;
  readonly direction: Direction;
  readonly point: LatLon;
  readonly azimuth?: number | null | undefined;
  readonly speedKmh?: number | null | undefined;
  readonly lowFloor: Accessibility;
}

export interface Stop {
  readonly id: string;
  readonly name: string;
  readonly point: LatLon;
}

export interface LineSummary {
  readonly line: Line;
  readonly vehiclesOnLine: number;
}

export interface LineVehicle {
  readonly vehicle: Vehicle;
  /** Номер следующей остановки в списке stops; null, если впереди остановок нет. */
  readonly nextStopOrder: number | null;
}

export interface LineDirection {
  readonly direction: Direction;
  readonly stops: readonly Stop[];
  readonly path: readonly LatLon[];
  readonly vehicles: readonly LineVehicle[];
}

export interface LineDetails {
  readonly line: Line;
  readonly directions: readonly LineDirection[];
}

export interface Meta {
  readonly appName: string;
  readonly version: string;
  readonly cityBounds: Bounds;
  readonly refreshIntervalS: number;
  readonly lowFloorOnlyDefault: boolean;
  readonly staleSeconds: number;
}

/** Что за место нашёл поиск адреса: от этого зависит подпись в подсказке. */
export type PlaceKind = 'address' | 'street' | 'stop' | 'place' | 'area';

export interface PlaceSuggestion {
  readonly id: string;
  readonly title: string;
  readonly subtitle: string | null;
  readonly kind: PlaceKind;
  readonly point: LatLon;
}

/** Точка А («Откуда») или Б («Куда»). */
export type Endpoint = 'from' | 'to';

export interface TripPoint {
  /** Что показать в поле: адрес, название или «Точка на карте». */
  readonly label: string;
  readonly point: LatLon;
}
