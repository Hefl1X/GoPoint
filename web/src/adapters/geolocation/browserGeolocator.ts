// Геолокация браузера. Вызывается только по кнопке; координаты никуда не отправляются
// и не сохраняются. Без HTTPS (кроме localhost) браузеры её не дают.
import type { LatLon } from '../../domain/types';
import { GeolocationError, type Geolocator } from '../../ports/Geolocation';

export const browserGeolocator: Geolocator = {
  locate() {
    return new Promise<LatLon>((resolve, reject) => {
      if (!window.isSecureContext) {
        reject(new GeolocationError('insecure'));
        return;
      }
      if (!('geolocation' in navigator)) {
        reject(new GeolocationError('unavailable'));
        return;
      }
      navigator.geolocation.getCurrentPosition(
        (position) => {
          resolve({ lat: position.coords.latitude, lon: position.coords.longitude });
        },
        (error) => {
          const reason =
            error.code === error.PERMISSION_DENIED
              ? 'denied'
              : error.code === error.TIMEOUT
                ? 'timeout'
                : 'unavailable';
          reject(new GeolocationError(reason));
        },
        { enableHighAccuracy: true, timeout: 15_000, maximumAge: 30_000 },
      );
    });
  },
};
