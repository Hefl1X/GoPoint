// Панорамы: ссылка на сайт Яндекс Карт. Приложение само ничего не загружает у Яндекса:
// ссылка открывается по нажатию, в новой вкладке. Если панорамы в точке нет,
// Яндекс Карты покажут обычную карту.
// Формат параметров (panorama[point], l=stv,sta) взят из адресной строки Яндекс Карт;
// в документации Яндекса он не описан, поэтому адрес проверяется вручную (docs/DECISIONS.md).
import type { StreetImagery } from '../../ports/StreetImagery';

const BASE = 'https://yandex.ru/maps/';

export function createYandexPanorama(): StreetImagery {
  return {
    panoramaUrl(point) {
      const lonLat = `${String(point.lon)},${String(point.lat)}`;
      const url = new URL(BASE);
      url.searchParams.set('panorama[point]', lonLat);
      url.searchParams.set('l', 'stv,sta');
      url.searchParams.set('ll', lonLat);
      return url.toString();
    },
  };
}
