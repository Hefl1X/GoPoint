// Точка сборки: какие адаптеры стоят за портами.
import '@fontsource/nunito/400.css';
import '@fontsource/nunito/600.css';
import '@fontsource/nunito/800.css';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { httpLiveApi } from './adapters/api/client';
import { browserGeolocator } from './adapters/geolocation/browserGeolocator';
import { chooseMapView } from './adapters/map';
import { createLocalStore } from './adapters/storage/localStore';
import { App } from './App';
import { ServicesProvider, type Services } from './shared/services';
import { SettingsProvider } from './shared/settings';
import './shared/base.css';

const services: Services = {
  api: httpLiveApi,
  store: createLocalStore(),
  geolocator: browserGeolocator,
  MapView: chooseMapView(),
};

const queryClient = new QueryClient();
const root = document.getElementById('root');
if (!root) throw new Error('Нет элемента #root в index.html');

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ServicesProvider services={services}>
        <SettingsProvider>
          <App />
        </SettingsProvider>
      </ServicesProvider>
    </QueryClientProvider>
  </StrictMode>,
);
