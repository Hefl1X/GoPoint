// Внешние сервисы приложения за портами. Конкретные адаптеры подставляет main.tsx,
// тесты подставляют заглушки.
import { createContext, useContext, type ReactNode } from 'react';
import type { Geolocator } from '../ports/Geolocation';
import type { LiveApi } from '../ports/LiveApi';
import type { MapView } from '../ports/MapView';
import type { KeyValueStore } from '../ports/Storage';

export interface Services {
  readonly api: LiveApi;
  readonly store: KeyValueStore;
  readonly geolocator: Geolocator;
  readonly MapView: MapView;
}

const ServicesContext = createContext<Services | null>(null);

export function ServicesProvider({
  services,
  children,
}: {
  services: Services;
  children: ReactNode;
}) {
  return <ServicesContext.Provider value={services}>{children}</ServicesContext.Provider>;
}

export function useServices(): Services {
  const services = useContext(ServicesContext);
  if (!services) throw new Error('ServicesProvider не подключён');
  return services;
}
