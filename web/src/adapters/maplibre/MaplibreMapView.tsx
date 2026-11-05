// Карта на MapLibre GL и векторных тайлах OpenFreeMap (данные OpenStreetMap).
// Только здесь известно про MapLibre и порядок координат [lon, lat].
import {
  Map as MapLibreMap,
  Marker,
  setWorkerUrl,
  type GeoJSONSource,
  type LngLatLike,
} from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useEffect, useRef, useState } from 'react';
import { ListMapView } from '../map-list/ListMapView';
import { MUTED_COLOR, TYPE_COLOR } from '../../domain/transport';
import type { Endpoint, LatLon, TransportType } from '../../domain/types';
import type { MapJourneyLine, MapTripPoint, MapVehicle, MapViewProps } from '../../ports/MapView';
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
          selected: v.id === selectedId,
        },
        geometry: { type: 'Point' as const, coordinates: toLngLat(v.point) },
      };
    }),
  };
}

const WALK_COLOR = '#17332e';

function journeyGeoJson(lines: readonly MapJourneyLine[] | undefined) {
  return {
    type: 'FeatureCollection' as const,
    features: (lines ?? [])
      .filter((l) => l.points.length > 1)
      .map((l) => ({
        type: 'Feature' as const,
        properties: { kind: l.kind, color: l.kind === 'walk' ? WALK_COLOR : l.color },
        geometry: { type: 'LineString' as const, coordinates: l.points.map(toLngLat) },
      })),
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

const END_LETTER: Record<Endpoint, string> = { from: 'А', to: 'Б' };

/** Значок точки: А зелёный круг с буквой, Б оранжевая булавка с буквой (DESIGN.md). */
export function tripMarkerElement(end: Endpoint): HTMLElement {
  // MapLibre двигает значок через transform внешнего элемента, поэтому форма
  // (повёрнутая булавка) рисуется во внутреннем.
  const wrap = document.createElement('div');
  wrap.className = 'trip-marker-wrap';
  wrap.setAttribute('role', 'img');
  const shape = document.createElement('div');
  shape.className = `trip-marker trip-marker--${end}`;
  const letter = document.createElement('span');
  letter.className = 'trip-marker__letter';
  letter.textContent = END_LETTER[end];
  shape.append(letter);
  wrap.append(shape);
  return wrap;
}

function syncTripMarkers(
  map: MapLibreMap,
  markers: Map<Endpoint, Marker>,
  points: readonly MapTripPoint[],
): void {
  for (const [end, marker] of markers) {
    if (!points.some((p) => p.end === end)) {
      marker.remove();
      markers.delete(end);
    }
  }
  for (const p of points) {
    let marker = markers.get(p.end);
    if (!marker) {
      marker = new Marker({
        element: tripMarkerElement(p.end),
        anchor: p.end === 'to' ? 'bottom' : 'center',
      });
      marker.setLngLat(toLngLat(p.point)).addTo(map);
      markers.set(p.end, marker);
    }
    marker.setLngLat(toLngLat(p.point));
    marker.getElement().setAttribute('aria-label', `Точка ${END_LETTER[p.end]}: ${p.label}`);
  }
}

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// Если стиль карты не загрузился за это время (сервер карты недоступен), показываем
// машины списком, а не пустой экран.
const STYLE_TIMEOUT_MS = 30_000;
const FAILED_NOTE = 'Карта сейчас не загружается. Транспорт на линии — списком ниже.';

export function MaplibreMapView(props: MapViewProps) {
  const [failed, setFailed] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const loaded = useRef(false);
  const markers = useRef(new Map<Endpoint, Marker>());
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
      // Подпись источников рисуем сами (ниже), стандартная закрывает кнопки на телефоне.
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
    });
    map.touchZoomRotate.disableRotation();
    mapRef.current = map;

    let styleLoaded = false;
    const giveUp = () => {
      if (styleLoaded) return;
      mapRef.current = null;
      map.remove();
      setFailed(true);
    };
    const timer = window.setTimeout(giveUp, STYLE_TIMEOUT_MS);
    map.on('style.load', () => {
      styleLoaded = true;
      window.clearTimeout(timer);
    });
    // Ошибка до загрузки стиля: стиль карты не получен. Ошибки отдельных тайлов
    // после загрузки не мешают: машины и маршрут рисуются поверх фона.
    map.on('error', () => {
      if (!styleLoaded) giveUp();
    });

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
      map.addSource('journey', { type: 'geojson', data: journeyGeoJson(undefined) });
      map.addLayer({
        id: 'journey-ride',
        type: 'line',
        source: 'journey',
        filter: ['==', ['get', 'kind'], 'ride'],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': ['get', 'color'], 'line-width': 6, 'line-opacity': 0.9 },
      });
      map.addLayer({
        id: 'journey-walk',
        type: 'line',
        source: 'journey',
        filter: ['==', ['get', 'kind'], 'walk'],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': ['get', 'color'], 'line-width': 4, 'line-dasharray': [1, 1.5] },
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
        filter: ['!', ['get', 'selected']],
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
      map.addLayer({
        id: 'vehicle-selected',
        type: 'symbol',
        source: 'vehicles',
        // Выбранная машина видна всегда, поверх остальных.
        filter: ['get', 'selected'],
        layout: {
          'icon-image': ['get', 'image'],
          'icon-text-fit': 'both',
          'icon-allow-overlap': true,
          'text-allow-overlap': true,
          'text-field': ['get', 'number'],
          'text-font': ['Noto Sans Bold'],
          'text-size': 15,
          'symbol-sort-key': ['get', 'order'],
        },
        paint: { 'text-color': ['get', 'textColor'] },
      });
      for (const layer of ['vehicles', 'vehicle-dots', 'vehicle-selected']) {
        map.on('click', layer, (event) => {
          if (latest.current.picking) return;
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

    // Выбор точки: нажатие переносит центр карты, центр сообщается после движения.
    map.on('click', (event) => {
      if (!latest.current.picking) return;
      map.easeTo({ center: event.lngLat, duration: prefersReducedMotion() ? 0 : 300 });
    });
    map.on('moveend', () => {
      if (!latest.current.picking) return;
      const c = map.getCenter();
      latest.current.onCenterChange?.({ lat: c.lat, lon: c.lng });
    });

    const tripMarkers = markers.current;
    return () => {
      window.clearTimeout(timer);
      loaded.current = false;
      tripMarkers.clear();
      if (mapRef.current === map) {
        mapRef.current = null;
        map.remove();
      }
    };
  }, []);

  // Значки А и Б (элементы страницы поверх карты, не зависят от загрузки стиля).
  const { tripPoints } = props;
  useEffect(() => {
    const map = mapRef.current;
    if (map) syncTripMarkers(map, markers.current, tripPoints);
  }, [tripPoints]);

  // Начали выбирать точку: сразу сообщаем, где центр карты.
  const { picking } = props;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !picking) return;
    const c = map.getCenter();
    latest.current.onCenterChange?.({ lat: c.lat, lon: c.lng });
  }, [picking]);

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
    moveTo(map, center, zoom, !focus.exact);
  }, [focus]);

  // Построен маршрут: карта показывает его целиком между карточкой сверху и панелью снизу.
  const { fitPoints } = props;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !fitPoints || fitPoints.length === 0) return;
    let [west, south, east, north] = [180, 90, -180, -90];
    for (const p of fitPoints) {
      west = Math.min(west, p.lon);
      east = Math.max(east, p.lon);
      south = Math.min(south, p.lat);
      north = Math.max(north, p.lat);
    }
    const height = map.getContainer().clientHeight;
    map.fitBounds(
      [
        [west, south],
        [east, north],
      ],
      {
        padding: { top: 150, bottom: Math.round(height * 0.45), left: 40, right: 40 },
        maxZoom: 16,
        duration: prefersReducedMotion() ? 0 : 600,
      },
    );
  }, [fitPoints]);

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

  if (failed) return <ListMapView {...props} note={FAILED_NOTE} />;

  return (
    <>
      <div
        ref={container}
        className="map-view"
        role="region"
        aria-label={props.label}
        data-testid="map-maplibre"
      />
      {/* Подпись источников карты (условия OpenStreetMap и OpenFreeMap): одна короткая
          строка вверху, всегда видна, не закрывает кнопки. */}
      <p className="map-attribution">
        ©{' '}
        <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
          OpenStreetMap contributors
        </a>{' '}
        ·{' '}
        <a href="https://openfreemap.org" target="_blank" rel="noreferrer">
          OpenFreeMap
        </a>{' '}
        © OpenMapTiles
      </p>
    </>
  );
}

/**
 * Точка встаёт чуть выше центра (сверху карточка «Откуда/Куда», снизу панель,
 * видимая часть карты между ними) или ровно в центр.
 */
function moveTo(map: MapLibreMap, center: [number, number], zoom: number, lift = true): void {
  const offset: [number, number] = [0, lift ? -map.getContainer().clientHeight * 0.15 : 0];
  map.easeTo({ center, zoom, offset, duration: prefersReducedMotion() ? 0 : 600 });
}

function sync(map: MapLibreMap, props: MapViewProps): void {
  void map
    .getSource<GeoJSONSource>('vehicles')
    ?.setData(vehiclesGeoJson(props.vehicles, props.selectedVehicleId));
  void map.getSource<GeoJSONSource>('route')?.setData(lineGeoJson(props.routeLine));
  void map.getSource<GeoJSONSource>('user')?.setData(pointGeoJson(props.userLocation));
  void map.getSource<GeoJSONSource>('journey')?.setData(journeyGeoJson(props.journeyLines));
  if (map.getLayer('route')) map.setPaintProperty('route', 'line-color', props.routeColor);
}
