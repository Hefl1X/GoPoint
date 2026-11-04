// Помощники для тестов: приложение с заглушками вместо сервера, карты и памяти.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderResult } from '@testing-library/react';
import type { ReactNode } from 'react';
import { vi } from 'vitest';
import { ListMapView } from './adapters/map-list/ListMapView';
import { createMemoryStore } from './adapters/storage/localStore';
import type { LineDetails, LineSummary, Meta, Vehicle } from './domain/types';
import type { Geolocator } from './ports/Geolocation';
import type { LiveApi } from './ports/LiveApi';
import type { KeyValueStore } from './ports/Storage';
import { ServicesProvider, type Services } from './shared/services';
import { SettingsProvider } from './shared/settings';

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

export function renderApp(
  ui: ReactNode,
  options: { api?: LiveApi; store?: KeyValueStore; geolocator?: Geolocator } = {},
): RenderResult & { services: Services } {
  const services: Services = {
    api: options.api ?? fakeApi(),
    store: options.store ?? createMemoryStore(),
    geolocator: options.geolocator ?? { locate: () => Promise.resolve({ lat: 55, lon: 83 }) },
    MapView: ListMapView,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const result = render(
    <QueryClientProvider client={client}>
      <ServicesProvider services={services}>
        <SettingsProvider>{ui}</SettingsProvider>
      </ServicesProvider>
    </QueryClientProvider>,
  );
  return { ...result, services };
}
