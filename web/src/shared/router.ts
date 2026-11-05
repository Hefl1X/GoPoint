// Простые переходы между экранами на hash-адресах (#/transport/bus-3).
// Работают «Назад» в браузере и жест «назад», не требуют настройки сервера
// и подойдут для оболочки Capacitor.
import { useEffect, useState } from 'react';
import type { Endpoint } from '../domain/types';

export type Route =
  | { readonly name: 'map'; readonly vehicleId: string | null }
  | { readonly name: 'search'; readonly end: Endpoint }
  | { readonly name: 'pick'; readonly end: Endpoint }
  | { readonly name: 'transport' }
  | { readonly name: 'line'; readonly lineId: string }
  | { readonly name: 'stop'; readonly stopId: string }
  | { readonly name: 'settings' }
  | { readonly name: 'about' }
  | { readonly name: 'install' };

export function parseRoute(hash: string): Route {
  const path = hash.replace(/^#/, '').replace(/^\//, '');
  const [first = '', second] = path.split('/');
  const decode = (s: string) => {
    try {
      return decodeURIComponent(s);
    } catch {
      // Испорченный адрес: считаем, что параметра нет.
      return '';
    }
  };
  const end: Endpoint = second === 'from' ? 'from' : 'to';
  switch (first) {
    case 'search':
      return { name: 'search', end };
    case 'pick':
      return { name: 'pick', end };
    case 'vehicle':
      return { name: 'map', vehicleId: second ? decode(second) || null : null };
    case 'transport':
      return second && decode(second)
        ? { name: 'line', lineId: decode(second) }
        : { name: 'transport' };
    case 'stop':
      return second && decode(second)
        ? { name: 'stop', stopId: decode(second) }
        : { name: 'transport' };
    case 'settings':
      return { name: 'settings' };
    case 'about':
      return { name: 'about' };
    case 'install':
      return { name: 'install' };
    default:
      return { name: 'map', vehicleId: null };
  }
}

export function routeHref(route: Route): string {
  switch (route.name) {
    case 'map':
      return route.vehicleId ? `#/vehicle/${encodeURIComponent(route.vehicleId)}` : '#/';
    case 'search':
      return `#/search/${route.end}`;
    case 'pick':
      return `#/pick/${route.end}`;
    case 'transport':
      return '#/transport';
    case 'line':
      return `#/transport/${encodeURIComponent(route.lineId)}`;
    case 'stop':
      return `#/stop/${encodeURIComponent(route.stopId)}`;
    case 'settings':
      return '#/settings';
    case 'about':
      return '#/about';
    case 'install':
      return '#/install';
  }
}

export function navigate(route: Route, options: { replace?: boolean } = {}): void {
  if (options.replace) {
    // Без новой записи в истории: «Назад» после выбора точки не открывает поиск снова.
    window.location.replace(routeHref(route));
  } else {
    window.location.hash = routeHref(route);
  }
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => {
      setRoute(parseRoute(window.location.hash));
    };
    window.addEventListener('hashchange', onChange);
    return () => {
      window.removeEventListener('hashchange', onChange);
    };
  }, []);
  return route;
}
