// Оболочка: текущий экран и нижняя панель «Карта, Транспорт, Настройки».
import { AboutScreen } from './features/about/AboutScreen';
import { InstallIosScreen } from './features/install/InstallIosScreen';
import { LiveRouteScreen } from './features/live-route/LiveRouteScreen';
import { LiveRoutesScreen } from './features/live-routes/LiveRoutesScreen';
import { LiveStopScreen } from './features/live-stop/LiveStopScreen';
import { SettingsScreen } from './features/settings/SettingsScreen';
import { MapScreen } from './features/start/MapScreen';
import { BottomNav } from './shared/components';
import { useRoute, type Route } from './shared/router';

function activeTab(route: Route) {
  if (route.name === 'transport' || route.name === 'line' || route.name === 'stop')
    return 'transport' as const;
  if (route.name === 'settings' || route.name === 'about' || route.name === 'install')
    return 'settings' as const;
  return 'map' as const;
}

export function App() {
  const route = useRoute();
  return (
    <div className="app">
      <div className="app__content">
        {/* Карта, поиск адреса и выбор точки: один и тот же экран, карта не пересоздаётся. */}
        {route.name === 'map' || route.name === 'search' || route.name === 'pick' ? (
          <MapScreen route={route} />
        ) : null}
        {route.name === 'transport' ? <LiveRoutesScreen /> : null}
        {route.name === 'line' ? (
          <LiveRouteScreen key={route.lineId} lineId={route.lineId} />
        ) : null}
        {route.name === 'stop' ? <LiveStopScreen key={route.stopId} stopId={route.stopId} /> : null}
        {route.name === 'settings' ? <SettingsScreen /> : null}
        {route.name === 'about' ? <AboutScreen /> : null}
        {route.name === 'install' ? <InstallIosScreen /> : null}
      </div>
      <BottomNav active={activeTab(route)} />
    </div>
  );
}
