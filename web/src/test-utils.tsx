// Помощники для тестов: приложение с заглушками вместо сервера, карты и памяти.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderResult } from '@testing-library/react';
import type { ReactNode } from 'react';
import { vi } from 'vitest';
import { ListMapView } from './adapters/map-list/ListMapView';
import { createMemoryStore } from './adapters/storage/localStore';
import type {
  LineDetails,
  LineSummary,
  Meta,
  PlaceSuggestion,
  TripPoint,
  Vehicle,
} from './domain/types';
import type { Geolocator } from './ports/Geolocation';
import type { LiveApi } from './ports/LiveApi';
import type { PlaceSearch } from './ports/PlaceSearch';
import type { KeyValueStore } from './ports/Storage';
import { ServicesProvider, type Services } from './shared/services';
import { SettingsProvider } from './shared/settings';
import { TripProvider } from './shared/trip';

export const META: Meta = {
  appName: 'GoPoint',
  version: '0.1.0',
  cityBounds: { southWest: { lat: 54.8, lon: 82.7 }, northEast: { lat: 55.2, lon: 83.2 } },
  refreshIntervalS: 30,
  lowFloorOnlyDefault: true,
  staleSeconds: 300,
};

export function vehicle(overrides: Partial<Vehicle> & { id: string }): Vehicle {
  return {
    lineId: 'bus-3',
    type: 'bus',
    number: '3',
    direction: 'A',
    point: { lat: 55.03, lon: 82.92 },
    azimuth: 90,
    speedKmh: 20,
    lowFloor: 'yes',
    ...overrides,
  };
}

const BUS_3_1 = vehicle({ id: 'bus-3-1' });

export const VEHICLES: Vehicle[] = [
  BUS_3_1,
  vehicle({ id: 'bus-3-2', lowFloor: 'no', direction: 'B' }),
  vehicle({
    id: 'tram-0013-4',
    lineId: 'tram-0013',
    type: 'tram',
    number: '13',
    lowFloor: 'unknown',
  }),
];

const BUS_3_LINE = { id: 'bus-3', type: 'bus', number: '3', title: 'Вокзал — Северный' } as const;

export const LINES: LineSummary[] = [
  {
    line: BUS_3_LINE,
    vehiclesOnLine: 2,
  },
  {
    line: { id: 'bus-36', type: 'bus', number: '36', title: 'Вокзал — Затулинка' },
    vehiclesOnLine: 0,
  },
  {
    line: { id: 'tram-0013', type: 'tram', number: '13', title: 'Шоссе — Писарева' },
    vehiclesOnLine: 1,
  },
];

const stop = (id: string, name: string) => ({ id, name, point: { lat: 55, lon: 82.9 } });

export const LINE_DETAILS: LineDetails = {
  line: BUS_3_LINE,
  directions: [
    {
      direction: 'A',
      stops: [stop('1', 'Вокзал'), stop('2', 'Цирк'), stop('3', 'Северный')],
      path: [
        { lat: 55, lon: 82.9 },
        { lat: 55.1, lon: 82.9 },
      ],
      vehicles: [
        { vehicle: BUS_3_1, nextStopOrder: 2 },
        { vehicle: vehicle({ id: 'bus-3-9', lowFloor: 'no' }), nextStopOrder: null },
      ],
    },
    {
      direction: 'B',
      stops: [stop('3', 'Северный'), stop('2', 'Цирк'), stop('1', 'Вокзал')],
      path: [],
      vehicles: [],
    },
  ],
};

export function fakeApi(overrides: Partial<LiveApi> = {}): LiveApi {
  return {
    getMeta: vi.fn(() => Promise.resolve(META)),
    getVehicles: vi.fn((lowFloorOnly: boolean) =>
      Promise.resolve(lowFloorOnly ? VEHICLES.filter((v) => v.lowFloor === 'yes') : VEHICLES),
    ),
    getLines: vi.fn(() => Promise.resolve(LINES)),
    getLine: vi.fn(() => Promise.resolve(LINE_DETAILS)),
    ...overrides,
  };
}

export const PLACES: PlaceSuggestion[] = [
  {
    id: 'osm-W1',
    title: 'Аура',
    subtitle: 'Военная улица, 5, Депутатский',
    kind: 'place',
    point: { lat: 55.0435, lon: 82.9227 },
  },
  {
    id: 'osm-W2',
    title: 'Красный проспект, 25/1',
    subtitle: 'Депутатский',
    kind: 'address',
    point: { lat: 55.0287, lon: 82.9195 },
  },
  {
    id: 'osm-N3',
    title: 'Цирк',
    subtitle: 'улица Челюскинцев',
    kind: 'stop',
    point: { lat: 55.04, lon: 82.91 },
  },
];

export function fakePlaces(overrides: Partial<PlaceSearch> = {}): PlaceSearch {
  return {
    search: vi.fn((q: string) =>
      Promise.resolve(PLACES.filter((p) => p.title.toLowerCase().includes(q.toLowerCase()))),
    ),
    reverse: vi.fn(() => Promise.resolve(PLACES[1] ?? null)),
    ...overrides,
  };
}

export function renderApp(
  ui: ReactNode,
  options: {
    api?: LiveApi;
    store?: KeyValueStore;
    geolocator?: Geolocator;
    places?: PlaceSearch;
    mapCanPick?: boolean;
    trip?: { from?: TripPoint | null; to?: TripPoint | null };
  } = {},
): RenderResult & { services: Services } {
  const services: Services = {
    api: options.api ?? fakeApi(),
    store: options.store ?? createMemoryStore(),
    geolocator: options.geolocator ?? { locate: () => Promise.resolve({ lat: 55, lon: 83 }) },
    MapView: ListMapView,
    mapCanPick: options.mapCanPick ?? false,
    places: options.places ?? fakePlaces(),
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const result = render(
    <QueryClientProvider client={client}>
      <ServicesProvider services={services}>
        <SettingsProvider>
          <TripProvider initial={options.trip}>{ui}</TripProvider>
        </SettingsProvider>
      </ServicesProvider>
    </QueryClientProvider>,
  );
  return { ...result, services };
}
