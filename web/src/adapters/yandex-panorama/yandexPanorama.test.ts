import { describe, expect, it } from 'vitest';
import { createYandexPanorama } from './yandexPanorama';

describe('ссылка на панораму в Яндекс Картах', () => {
  const url = new URL(createYandexPanorama().panoramaUrl({ lat: 55.0302, lon: 82.9204 }));

  it('ведёт на сайт Яндекс Карт', () => {
    expect(url.origin).toBe('https://yandex.ru');
    expect(url.pathname).toBe('/maps/');
  });

  it('точка в порядке «долгота, широта», включён слой панорам', () => {
    expect(url.searchParams.get('panorama[point]')).toBe('82.9204,55.0302');
    expect(url.searchParams.get('l')).toBe('stv,sta');
    expect(url.searchParams.get('ll')).toBe('82.9204,55.0302');
  });

  it('в ссылке нет ничего о человеке, только точка остановки', () => {
    expect([...url.searchParams.keys()].sort()).toEqual(['l', 'll', 'panorama[point]']);
  });
});
