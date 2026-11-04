// Простые переходы между экранами на hash-адресах (#/transport/bus-3).
// Работают «Назад» в браузере и жест «назад», не требуют настройки сервера
// и подойдут для оболочки Capacitor.
import { useEffect, useState } from 'react';

export type Route =
  | { readonly name: 'map'; readonly vehicleId: string | null }
  | { readonly name: 'transport' }
  | { readonly name: 'line'; readonly lineId: string }
  | { readonly name: 'settings' }
  | { readonly name: 'about' };

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
  switch (first) {
    case 'vehicle':
      return { name: 'map', vehicleId: second ? decode(second) || null : null };
    case 'transport':
      return second && decode(second)
        ? { name: 'line', lineId: decode(second) }
        : { name: 'transport' };
    case 'settings':
      return { name: 'settings' };
    case 'about':
      return { name: 'about' };
    default:
      return { name: 'map', vehicleId: null };
  }
}

export function routeHref(route: Route): string {
  switch (route.name) {
    case 'map':
      return route.vehicleId ? `#/vehicle/${encodeURIComponent(route.vehicleId)}` : '#/';
    case 'transport':
      return '#/transport';
    case 'line':
      return `#/transport/${encodeURIComponent(route.lineId)}`;
    case 'settings':
      return '#/settings';
    case 'about':
      return '#/about';
  }
}

export function navigate(route: Route): void {
  window.location.hash = routeHref(route);
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
