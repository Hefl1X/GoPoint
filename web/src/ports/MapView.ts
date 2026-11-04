// Порт карты. Реализации: adapters/maplibre (векторная карта) и adapters/map-list
// (список вместо карты, если WebGL недоступен). Координаты только { lat, lon }.
import type { ComponentType } from 'react';
import type { Accessibility, Bounds, LatLon, TransportType } from '../domain/types';

export interface MapVehicle {
  readonly id: string;
  readonly number: string;
  readonly type: TransportType;
  readonly lowFloor: Accessibility;
  readonly point: LatLon;
  /** Машина не из выбранного маршрута: показывается серой. */
  readonly muted: boolean;
}

export interface MapViewProps {
  /** Подпись для экранной читалки. */
  readonly label: string;
  /** Карта не уходит за эти границы. */
  readonly bounds: Bounds;
  readonly vehicles: readonly MapVehicle[];
  /** Выбранная машина; при смене выбора карта показывает её. */
  readonly selectedVehicleId: string | null;
  /** Линия выбранного маршрута и её цвет. */
  readonly routeLine: readonly LatLon[] | null;
  readonly routeColor: string;
  readonly userLocation: LatLon | null;
  /** Куда переместить карту; новый объект означает новое перемещение. */
  readonly focus: { readonly point: LatLon } | null;
  readonly onVehicleSelect: (id: string) => void;
}

export type MapView = ComponentType<MapViewProps>;
