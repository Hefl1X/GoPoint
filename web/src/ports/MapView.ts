// Порт карты. Реализации: adapters/maplibre (векторная карта) и adapters/map-list
// (список вместо карты, если WebGL недоступен). Координаты только { lat, lon }.
import type { ComponentType } from 'react';
import type { Accessibility, Bounds, Endpoint, LatLon, TransportType } from '../domain/types';

export interface MapVehicle {
  readonly id: string;
  readonly number: string;
  readonly type: TransportType;
  readonly lowFloor: Accessibility;
  readonly point: LatLon;
  /** Машина не из выбранного маршрута: показывается серой. */
  readonly muted: boolean;
}

/** Точка А или Б на карте. */
export interface MapTripPoint {
  readonly end: Endpoint;
  readonly point: LatLon;
  readonly label: string;
}

/** Кусок построенного маршрута: пешком (пунктир) или поездка (цвет маршрута). */
export interface MapJourneyLine {
  readonly kind: 'walk' | 'ride';
  readonly points: readonly LatLon[];
  readonly color: string;
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
  /** Построенный маршрут (пешие участки и поездки). */
  readonly journeyLines?: readonly MapJourneyLine[] | undefined;
  /** Показать все эти точки сразу; новый массив означает новое перемещение. */
  readonly fitPoints?: readonly LatLon[] | null | undefined;
  /** Точки А и Б. */
  readonly tripPoints: readonly MapTripPoint[];
  /**
   * Куда переместить карту; новый объект означает новое перемещение.
   * exact: точка ровно в центре карты (для выбора точки), иначе чуть выше центра,
   * потому что низ экрана закрыт панелью.
   */
  readonly focus: { readonly point: LatLon; readonly exact?: boolean } | null;
  /**
   * Режим «Выбрать на карте»: машины не выбираются, нажатие на карту переносит туда
   * центр, а центр карты сообщается через onCenterChange после каждого движения.
   */
  readonly picking: boolean;
  readonly onCenterChange?: ((center: LatLon) => void) | undefined;
  readonly onVehicleSelect: (id: string) => void;
}

export type MapView = ComponentType<MapViewProps>;
