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

const inMin = (m: number) => new Date(Date.now() + m * 60_000).toISOString();

const bus = (number: string) => ({ id: `bus-${number}`, type: 'bus', number, title: '' });

/** Маршрут в форме ответа сервера: пешком 6 мин, автобус через 10 мин, пешком 4 мин. */
export function journeyBody(number = '3', vehicleId = 'bus-3-1', lowFloor = 'yes', arrive = 26) {
  return {
    legs: [
      {
        kind: 'walk',
        origin: { name: null, point: point(55.0287, 82.9366) },
        destination: { name: 'Университет', point: point(55.03, 82.93) },
        distanceM: 290,
        durationS: 360,
        geometry: [point(55.0287, 82.9366), point(55.03, 82.93)],
        hasStairs: false,
      },
      {
        kind: 'transit',
        vehicleId,
        line: bus(number),
        lowFloor,
        boardStop: stop('10', 'Университет'),
        alightStop: stop('11', 'Площадь Маркса'),
        waitS: 240,
        stopsCount: 7,
        stopsAway: 2,
        toward: 'Северный',
        departAt: inMin(10),
        arriveAt: inMin(arrive - 4),
        diagnostics: { method: 'distance', positionObservedAt: observed },
        geometry: [point(55.03, 82.93), point(55.04, 82.91)],
      },
      {
        kind: 'walk',
        origin: { name: 'Площадь Маркса', point: point(55.04, 82.91) },
        destination: { name: null, point: point(55.0287, 82.9195) },
        distanceM: 190,
        durationS: 240,
        geometry: [point(55.04, 82.91), point(55.0287, 82.9195)],
        hasStairs: false,
      },
    ],
    departAt: inMin(0),
    arriveAt: inMin(arrive),
    durationS: arrive * 60,
    transfers: 0,
    lowFloorOnly: lowFloor === 'yes',
  };
}

export const ALL_VEHICLES = [vehicle('bus-3-1', 'yes'), vehicle('bus-3-2', 'no', 'B')];

export async function mockServer(
  page: Page,
  options: {
    failLive?: boolean;
    vehiclesDelayMs?: number;
    searchDown?: boolean;
    searchDelayMs?: number;
    noTransit?: boolean;
    routeDelayMs?: number;
    /** Первая машина маршрута встала: пересчёт предлагает другой автобус. */
    vehicleStopped?: boolean;
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
    if (path === '/route') {
      if (options.routeDelayMs) await new Promise((r) => setTimeout(r, options.routeDelayMs));
      if (options.noTransit) {
        return route.fulfill({
          json: {
            journeys: [],
            status: 'no_transit',
            message: 'Транспорта сейчас нет',
            diagnostics,
          },
        });
      }
      const body = route.request().postDataJSON() as { lowFloorOnly: boolean };
      return route.fulfill({
        json: {
          journeys: [journeyBody('3', 'bus-3-1', body.lowFloorOnly ? 'yes' : 'no')],
          status: 'ok',
          message: null,
          diagnostics,
        },
      });
    }
    if (path === '/route/check') {
      const body = route.request().postDataJSON() as { vehicleId: string; lowFloorOnly: boolean };
      const low = body.lowFloorOnly ? 'yes' : 'no';
      if (options.vehicleStopped && body.vehicleId === 'bus-3-1') {
        return route.fulfill({
          json: {
            status: 'stopped',
            stoppedForS: 540,
            current: journeyBody('3', 'bus-3-1', 'yes', 35),
            alternative: journeyBody('36', 'bus-36-1', 'yes', 24),
            gainS: 660,
            diagnostics,
          },
        });
      }
      return route.fulfill({
        json: {
          status: 'ok',
          stoppedForS: null,
          current: journeyBody(body.vehicleId === 'bus-36-1' ? '36' : '3', body.vehicleId, low),
          alternative: null,
          diagnostics,
        },
      });
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
    if (path === '/live/stops/2/arrivals') {
      const tram = {
        ...vehicle('tram-0013-4', 'unknown'),
        lineId: 'tram-0013',
        type: 'tram',
        number: '13',
      };
      const arrivals = [
        {
          vehicle: ALL_VEHICLES[0],
          toward: 'Северный',
          stopsAway: 2,
          arriveAt: inMin(4),
          diagnostics: { method: 'distance', positionObservedAt: observed },
        },
        {
          vehicle: tram,
          toward: 'Писарева',
          stopsAway: 6,
          arriveAt: inMin(12),
          diagnostics: { method: 'planned', positionObservedAt: observed },
        },
      ];
      return route.fulfill({
        json: {
          stop: stop('2', 'Цирк'),
          arrivals: lowFloorOnly ? arrivals.slice(0, 1) : arrivals,
          diagnostics,
        },
      });
    }
    if (path.startsWith('/live/vehicles/')) {
      const id = decodeURIComponent(path.slice('/live/vehicles/'.length));
      const found = ALL_VEHICLES.find((v) => v.id === id);
      if (!found) {
        return route.fulfill({
          status: 404,
          json: { code: 'VEHICLE_NOT_FOUND', message: 'Этой машины сейчас нет на линии.' },
        });
      }
      const eta = (m: number) => ({
        arriveAt: inMin(m),
        diagnostics: { method: 'distance', positionObservedAt: observed },
      });
      return route.fulfill({
        json: {
          vehicle: found,
          toward: 'Северный',
          nextStops: [
            { stop: stop('2', 'Цирк'), ...eta(2) },
            { stop: stop('3', 'Северный'), ...eta(15) },
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
