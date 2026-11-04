// Оболочка: текущий экран и нижняя панель «Карта, Транспорт, Настройки».
import { AboutScreen } from './features/about/AboutScreen';
import { LiveRouteScreen } from './features/live-route/LiveRouteScreen';
import { LiveRoutesScreen } from './features/live-routes/LiveRoutesScreen';
import { SettingsScreen } from './features/settings/SettingsScreen';
import { MapScreen } from './features/start/MapScreen';
import { BottomNav } from './shared/components';
import { useRoute, type Route } from './shared/router';

function activeTab(route: Route) {
  if (route.name === 'transport' || route.name === 'line') return 'transport' as const;
  if (route.name === 'settings' || route.name === 'about') return 'settings' as const;
  return 'map' as const;
}

export function App() {
  const route = useRoute();
  return (
    <div className="app">
      <div className="app__content">
        {route.name === 'map' ? <MapScreen vehicleId={route.vehicleId} /> : null}
        {route.name === 'transport' ? <LiveRoutesScreen /> : null}
        {route.name === 'line' ? (
          <LiveRouteScreen key={route.lineId} lineId={route.lineId} />
        ) : null}
        {route.name === 'settings' ? <SettingsScreen /> : null}
        {route.name === 'about' ? <AboutScreen /> : null}
      </div>
      <BottomNav active={activeTab(route)} />
    </div>
  );
}
