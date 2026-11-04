// Карта на MapLibre GL и векторных тайлах OpenFreeMap (данные OpenStreetMap).
// Только здесь известно про MapLibre и порядок координат [lon, lat].
import {
  AttributionControl,
  Map as MapLibreMap,
  setWorkerUrl,
  type GeoJSONSource,
  type LngLatLike,
} from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useEffect, useRef } from 'react';
import { MUTED_COLOR, TYPE_COLOR } from '../../domain/transport';
import type { LatLon, TransportType } from '../../domain/types';
import type { MapVehicle, MapViewProps } from '../../ports/MapView';
import { STYLE_URL } from './config';

setWorkerUrl(workerUrl);

const NOVOSIBIRSK_CENTER: LngLatLike = [82.92, 55.03];
const PILL_PIXEL_RATIO = 2;

const toLngLat = (p: LatLon): [number, number] => [p.lon, p.lat];

type PillStyle = 'filled' | 'outline';

function pillImageName(type: TransportType | 'muted', style: PillStyle): string {
  return `gopoint-pill-${type}-${style}`;
}

/** Растягиваемая «таблетка»: цвет вида транспорта, без низкого пола только контур. */
function drawPill(color: string, style: PillStyle): ImageData {
  const w = 40 * PILL_PIXEL_RATIO;
  const h = 28 * PILL_PIXEL_RATIO;
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Canvas 2D недоступен');
  const line = 3 * PILL_PIXEL_RATIO;
  const r = h / 2 - line;
  ctx.beginPath();
  ctx.roundRect(line, line, w - 2 * line, h - 2 * line, r);
  ctx.fillStyle = style === 'filled' ? color : '#ffffff';
  ctx.fill();
  ctx.lineWidth = line;
  ctx.strokeStyle = style === 'filled' ? '#ffffff' : color;
  ctx.stroke();
  return ctx.getImageData(0, 0, w, h);
}

function addPillImages(map: MapLibreMap): void {
  const variants: [TransportType | 'muted', string][] = [
    ...(Object.entries(TYPE_COLOR) as [TransportType, string][]),
    ['muted', MUTED_COLOR],
  ];
  const mid = 20 * PILL_PIXEL_RATIO;
  for (const [type, color] of variants) {
    for (const style of ['filled', 'outline'] as const) {
      const name = pillImageName(type, style);
      if (map.hasImage(name)) continue;
      map.addImage(name, drawPill(color, style), {
        pixelRatio: PILL_PIXEL_RATIO,
        stretchX: [[mid - 4, mid + 4]],
        stretchY: [[26, 30]],
        content: [
          10 * PILL_PIXEL_RATIO,
          4 * PILL_PIXEL_RATIO,
          30 * PILL_PIXEL_RATIO,
          24 * PILL_PIXEL_RATIO,
        ],
      });
    }
  }
}

function vehiclesGeoJson(vehicles: readonly MapVehicle[], selectedId: string | null) {
  return {
    type: 'FeatureCollection' as const,
    features: vehicles.map((v) => {
      const style: PillStyle = v.lowFloor === 'yes' ? 'filled' : 'outline';
      const colorKey = v.muted ? 'muted' : v.type;
      return {
        type: 'Feature' as const,
        id: v.id,
        properties: {
          id: v.id,
          number: v.number,
          image: pillImageName(colorKey, style),
          textColor: style === 'filled' ? '#ffffff' : v.muted ? MUTED_COLOR : TYPE_COLOR[v.type],
          // Выбранная машина сверху остальных.
          order: v.id === selectedId ? 2 : v.muted ? 0 : 1,
          color: v.muted ? MUTED_COLOR : TYPE_COLOR[v.type],
          filled: style === 'filled',
        },
        geometry: { type: 'Point' as const, coordinates: toLngLat(v.point) },
      };
    }),
  };
}

function lineGeoJson(points: readonly LatLon[] | null) {
  return {
    type: 'FeatureCollection' as const,
    features:
      points && points.length > 1
        ? [
            {
              type: 'Feature' as const,
              properties: {},
              geometry: { type: 'LineString' as const, coordinates: points.map(toLngLat) },
            },
          ]
        : [],
  };
}

function pointGeoJson(point: LatLon | null) {
  return {
    type: 'FeatureCollection' as const,
    features: point
      ? [
          {
            type: 'Feature' as const,
            properties: {},
            geometry: { type: 'Point' as const, coordinates: toLngLat(point) },
          },
        ]
      : [],
  };
}

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function MaplibreMapView(props: MapViewProps) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const loaded = useRef(false);
  const latest = useRef(props);
  useEffect(() => {
    latest.current = props;
  });

  // Карта создаётся один раз.
  useEffect(() => {
    if (!container.current) return;
    const { bounds } = latest.current;
    const map = new MapLibreMap({
      container: container.current,
      style: STYLE_URL,
      center: NOVOSIBIRSK_CENTER,
      zoom: 11.5,
      minZoom: 9,
      maxZoom: 18,
      maxBounds: [
        [bounds.southWest.lon - 0.2, bounds.southWest.lat - 0.1],
        [bounds.northEast.lon + 0.2, bounds.northEast.lat + 0.1],
      ],
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
    });
    map.touchZoomRotate.disableRotation();
    // Наверху: внизу карту закрывает панель.
    map.addControl(
      new AttributionControl({ compact: true, customAttribution: '© OpenStreetMap contributors' }),
      'top-left',
    );
    mapRef.current = map;

    map.on('load', () => {
      addPillImages(map);
      map.addSource('route', { type: 'geojson', data: lineGeoJson(null) });
      map.addLayer({
        id: 'route',
        type: 'line',
        source: 'route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': latest.current.routeColor, 'line-width': 5, 'line-opacity': 0.85 },
      });
      map.addSource('user', { type: 'geojson', data: pointGeoJson(null) });
      map.addLayer({
        id: 'user',
        type: 'circle',
        source: 'user',
        paint: {
          'circle-radius': 8,
          'circle-color': '#0f6b5c',
          'circle-stroke-width': 3,
          'circle-stroke-color': '#ffffff',
        },
      });
      map.addSource('vehicles', { type: 'geojson', data: vehiclesGeoJson([], null) });
      // Точка под каждой машиной: видна всегда, даже если номеру не хватило места.
      map.addLayer({
        id: 'vehicle-dots',
        type: 'circle',
        source: 'vehicles',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 3, 15, 6],
          'circle-color': ['case', ['get', 'filled'], ['get', 'color'], '#ffffff'],
          'circle-stroke-color': ['get', 'color'],
          'circle-stroke-width': ['case', ['get', 'filled'], 1, 2],
        },
      });
      map.addLayer({
        id: 'vehicles',
        type: 'symbol',
        source: 'vehicles',
        layout: {
          'icon-image': ['get', 'image'],
          'icon-text-fit': 'both',
          // Номера не налезают друг на друга: лишние прячутся до приближения карты.
          'icon-allow-overlap': false,
          'text-allow-overlap': false,
          'text-field': ['get', 'number'],
          'text-font': ['Noto Sans Bold'],
          'text-size': 13,
          'symbol-sort-key': ['get', 'order'],
        },
        paint: { 'text-color': ['get', 'textColor'] },
      });
      for (const layer of ['vehicles', 'vehicle-dots']) {
        map.on('click', layer, (event) => {
          const id: unknown = event.features?.[0]?.properties.id;
          if (typeof id === 'string') latest.current.onVehicleSelect(id);
        });
        map.on('mouseenter', layer, () => {
          map.getCanvas().style.cursor = 'pointer';
        });
        map.on('mouseleave', layer, () => {
          map.getCanvas().style.cursor = '';
        });
      }
      loaded.current = true;
      sync(map, latest.current);
    });

    return () => {
      loaded.current = false;
      mapRef.current = null;
      map.remove();
    };
  }, []);

  // Данные обновляются без пересоздания карты.
  useEffect(() => {
    const map = mapRef.current;
    if (map && loaded.current) sync(map, props);
  }, [props]);

  // Перемещение карты по запросу (моё местоположение, выбранная машина).
  const { focus } = props;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !focus) return;
    const center = toLngLat(focus.point);
    const zoom = Math.max(map.getZoom(), 14);
    moveTo(map, center, zoom);
  }, [focus]);

  // Выбрали машину: карта переезжает к ней один раз (а не за каждым её движением).
  const { selectedVehicleId } = props;
  const selectedVisible = props.vehicles.some((v) => v.id === selectedVehicleId);
  useEffect(() => {
    const map = mapRef.current;
    const vehicle = latest.current.vehicles.find((v) => v.id === selectedVehicleId);
    if (!map || !vehicle) return;
    const center = toLngLat(vehicle.point);
    const zoom = Math.max(map.getZoom(), 14);
    moveTo(map, center, zoom);
  }, [selectedVehicleId, selectedVisible]);

  return (
    <div
      ref={container}
      className="map-view"
      role="region"
      aria-label={props.label}
      data-testid="map-maplibre"
    />
  );
}

/** Точка встаёт в верхнюю четверть карты: низ экрана закрыт панелью. */
function moveTo(map: MapLibreMap, center: [number, number], zoom: number): void {
  const offset: [number, number] = [0, -map.getContainer().clientHeight * 0.25];
  map.easeTo({ center, zoom, offset, duration: prefersReducedMotion() ? 0 : 600 });
}

function sync(map: MapLibreMap, props: MapViewProps): void {
  void map
    .getSource<GeoJSONSource>('vehicles')
    ?.setData(vehiclesGeoJson(props.vehicles, props.selectedVehicleId));
  void map.getSource<GeoJSONSource>('route')?.setData(lineGeoJson(props.routeLine));
  void map.getSource<GeoJSONSource>('user')?.setData(pointGeoJson(props.userLocation));
  if (map.getLayer('route')) map.setPaintProperty('route', 'line-color', props.routeColor);
}
