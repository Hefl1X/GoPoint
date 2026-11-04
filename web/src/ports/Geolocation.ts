// Порт геолокации. Вызывается только по нажатию кнопки.
import type { LatLon } from '../domain/types';

export type GeolocationFailure = 'denied' | 'unavailable' | 'insecure' | 'timeout';

export interface Geolocator {
  locate(): Promise<LatLon>;
}

export class GeolocationError extends Error {
  readonly reason: GeolocationFailure;

  constructor(reason: GeolocationFailure) {
    super(reason);
    this.name = 'GeolocationError';
    this.reason = reason;
  }
}
