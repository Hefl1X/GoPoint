// Подменённый сервер GoPoint для e2e: сеть наружу не используется,
// тайлы карты не загружаются.
import type { Page, Route } from '@playwright/test';

const point = (lat: number, lon: number) => ({ lat, lon });
const observed = '2026-11-04T05:27:31Z';

const vehicle = (id: string, lowFloor: 'yes' | 'no' | 'unknown', direction: 'A' | 'B' = 'A') => ({
  id,
  lineId: 'bus-3',
  type: 'bus',
  number: '3',
  direction,
  point: point(55.03, 82.92),
  azimuth: 90,
  speedKmh: 20,
  lowFloor,
  positionObservedAt: observed,
});

const diagnostics = { fetchedAt: observed, complete: true };
const stop = (id: string, name: string) => ({ id, name, point: point(55.03, 82.92) });

export const PLACES = [
  {
    id: 'osm-W79524744',
    title: 'Аура',
    subtitle: 'Военная улица, 5, Депутатский',
    kind: 'place',
    point: point(55.0287, 82.9366),
  },
  {
    id: 'osm-W85290536',
    title: 'Красный проспект, 25/1',
    subtitle: 'Депутатский',
    kind: 'address',
    point: point(55.0287, 82.9195),
  },
  {
    id: 'osm-N1',
    title: 'Цирк',
    subtitle: 'улица Челюскинцев',
    kind: 'stop',
    point: point(55.04, 82.91),
  },
];

export const ALL_VEHICLES = [vehicle('bus-3-1', 'yes'), vehicle('bus-3-2', 'no', 'B')];

export async function mockServer(
  page: Page,
  options: {
    failLive?: boolean;
    vehiclesDelayMs?: number;
    searchDown?: boolean;
    searchDelayMs?: number;
  } = {},
): Promise<{ vehicleCalls: () => number; searchQueries: () => string[] }> {
  let vehicleCalls = 0;
  const searchQueries: string[] = [];
  await page.route('https://tiles.openfreemap.org/**', (route) => route.abort());
  await page.route('**/api/v1/**', async (route: Route) => {
    const url = new URL(route.request().url());
    const lowFloorOnly = url.searchParams.get('lowFloorOnly') !== 'false';
    const path = url.pathname.replace('/api/v1', '');
    if (options.failLive && path.startsWith('/live')) return route.abort('internetdisconnected');
    if (path === '/meta') {
      return route.fulfill({
        json: {
          appName: 'GoPoint',
          version: '0.1.0',
          cityBounds: { southWest: point(54.8, 82.7), northEast: point(55.2, 83.2) },
          refreshIntervalS: 30,
          lowFloorOnlyDefault: true,
          staleSeconds: 300,
        },
      });
    }
    if (path === '/search') {
      const q = url.searchParams.get('q') ?? '';
      searchQueries.push(q);
      if (options.searchDelayMs) await new Promise((r) => setTimeout(r, options.searchDelayMs));
      if (options.searchDown) {
        return route.fulfill({
          status: 503,
          json: {
            code: 'GEOCODER_UNAVAILABLE',
            message: 'Поиск адресов сейчас не работает. Выберите точку на карте.',
          },
        });
      }
      const places = PLACES.filter((p) => p.title.toLowerCase().includes(q.toLowerCase()));
      return route.fulfill({ json: { places } });
    }
    if (path === '/search/reverse') {
      return route.fulfill({ json: { place: PLACES[1] } });
    }
    if (path === '/live/vehicles') {
      vehicleCalls += 1;
      if (options.vehiclesDelayMs) await new Promise((r) => setTimeout(r, options.vehiclesDelayMs));
      const vehicles = lowFloorOnly
        ? ALL_VEHICLES.filter((v) => v.lowFloor === 'yes')
        : ALL_VEHICLES;
      return route.fulfill({ json: { vehicles, diagnostics } });
    }
    if (path === '/live/routes') {
      return route.fulfill({
        json: {
          lines: [
            {
              line: { id: 'bus-3', type: 'bus', number: '3', title: 'Вокзал — Северный' },
              vehiclesOnLine: lowFloorOnly ? 1 : 2,
            },
            {
              line: { id: 'tram-0013', type: 'tram', number: '13', title: 'Шоссе — Писарева' },
              vehiclesOnLine: lowFloorOnly ? 0 : 1,
            },
          ],
          diagnostics,
        },
      });
    }
    if (path === '/live/routes/bus-3') {
      return route.fulfill({
        json: {
          line: { id: 'bus-3', type: 'bus', number: '3', title: 'Вокзал — Северный' },
          directions: [
            {
              direction: 'A',
              stops: [stop('1', 'Вокзал'), stop('2', 'Цирк'), stop('3', 'Северный')],
              path: [point(55.03, 82.9), point(55.05, 82.92)],
              vehicles: [{ vehicle: ALL_VEHICLES[0], nextStopOrder: 1 }],
            },
            {
              direction: 'B',
              stops: [stop('3', 'Северный'), stop('2', 'Цирк'), stop('1', 'Вокзал')],
              path: [point(55.05, 82.92), point(55.03, 82.9)],
              vehicles: lowFloorOnly ? [] : [{ vehicle: ALL_VEHICLES[1], nextStopOrder: 2 }],
            },
          ],
          diagnostics,
        },
      });
    }
    return route.fulfill({
      status: 404,
      json: { code: 'NOT_FOUND', message: 'Ничего не нашлось по этому адресу.' },
    });
  });
  return { vehicleCalls: () => vehicleCalls, searchQueries: () => searchQueries };
}
