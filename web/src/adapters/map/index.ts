// Выбор адаптера карты: MapLibre, если браузер умеет WebGL, иначе список.
// ?map=list в адресе включает список принудительно (для проверок).
import { lazy } from 'react';
import type { MapView } from '../../ports/MapView';
import { ListMapView } from '../map-list/ListMapView';

function webglSupported(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(canvas.getContext('webgl2') ?? canvas.getContext('webgl'));
  } catch {
    // Браузер запретил WebGL: показываем список.
    return false;
  }
}

export function chooseMapView(): MapView {
  const forced = new URLSearchParams(window.location.search).get('map');
  if (forced === 'list' || !webglSupported()) return ListMapView;
  // Библиотека карты большая: грузим её отдельно, после оболочки сайта.
  return lazy(() =>
    import('../maplibre/MaplibreMapView').then((m) => ({ default: m.MaplibreMapView })),
  );
}
