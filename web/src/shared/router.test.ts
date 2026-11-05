import { describe, expect, it } from 'vitest';
import { parseRoute, routeHref, type Route } from './router';

describe('адреса экранов', () => {
  it.each<[string, Route]>([
    ['', { name: 'map', vehicleId: null }],
    ['#/', { name: 'map', vehicleId: null }],
    ['#/vehicle/bus-3-1', { name: 'map', vehicleId: 'bus-3-1' }],
    ['#/transport', { name: 'transport' }],
    ['#/transport/minibus-30%D0%90', { name: 'line', lineId: 'minibus-30А' }],
    ['#/stop/1418', { name: 'stop', stopId: '1418' }],
    ['#/stop', { name: 'transport' }],
    ['#/settings', { name: 'settings' }],
    ['#/about', { name: 'about' }],
    ['#/search/from', { name: 'search', end: 'from' }],
    ['#/search/to', { name: 'search', end: 'to' }],
    ['#/pick/to', { name: 'pick', end: 'to' }],
    ['#/pick/куда', { name: 'pick', end: 'to' }],
    ['#/непонятно', { name: 'map', vehicleId: null }],
    ['#/transport/%E0%A4%A', { name: 'transport' }],
  ])('%s', (hash, route) => {
    expect(parseRoute(hash)).toEqual(route);
  });

  it('туда и обратно', () => {
    const routes: Route[] = [
      { name: 'map', vehicleId: 'tram-0013-4' },
      { name: 'line', lineId: 'minibus-30А' },
      { name: 'settings' },
      { name: 'stop', stopId: 'ост 5' },
      { name: 'search', end: 'from' },
      { name: 'pick', end: 'to' },
    ];
    for (const route of routes) expect(parseRoute(routeHref(route))).toEqual(route);
  });
});
