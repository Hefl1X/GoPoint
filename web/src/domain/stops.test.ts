import { describe, expect, it } from 'vitest';
import { MIN_STOPS_ZOOM, stopsArea } from './stops';

const bounds = { southWest: { lat: 55, lon: 82.9 }, northEast: { lat: 55.01, lon: 82.92 } };

describe('остановки на карте', () => {
  it('на мелком масштабе остановки не запрашиваем и не рисуем', () => {
    expect(stopsArea({ bounds, zoom: MIN_STOPS_ZOOM - 0.5 })).toBeNull();
  });

  it('с приближением берём видимую область', () => {
    expect(stopsArea({ bounds, zoom: MIN_STOPS_ZOOM })).toEqual(bounds);
  });

  it('пока карта не сообщила область, остановок нет', () => {
    expect(stopsArea(null)).toBeNull();
  });
});
