// Порт «вид места с улицы» (панорама). Реализация: adapters/yandex-panorama.
// Заменить на другой сервис (например, Panoramax) можно, поменяв только адаптер.
import type { LatLon } from '../domain/types';

export interface StreetImagery {
  /** Ссылка, по которой человек откроет вид улицы у точки. Наружу уходит только точка. */
  panoramaUrl(point: LatLon): string;
}
