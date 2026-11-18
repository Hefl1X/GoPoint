// Стандартная растровая карта OSM. Подписи транспорта используют файлы из сборки сайта.
import type { StyleSpecification } from 'maplibre-gl';
import regularCyrillic from '@fontsource/nunito/files/nunito-cyrillic-400-normal.woff2?url';
import regularLatin from '@fontsource/nunito/files/nunito-latin-400-normal.woff2?url';
import boldCyrillic from '@fontsource/nunito/files/nunito-cyrillic-800-normal.woff2?url';
import boldLatin from '@fontsource/nunito/files/nunito-latin-800-normal.woff2?url';

export const BASEMAP = 'osm-standard';
const tileUrl =
  (import.meta.env.VITE_OSM_TILE_URL as string | undefined) ||
  'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

function fontFiles(cyrillic: string, latin: string) {
  return [{ url: cyrillic, 'unicode-range': ['U+0400-045F', 'U+2116'] }, { url: latin }];
}

export const mapStyle: StyleSpecification = {
  version: 8,
  'font-faces': {
    'Nunito Regular': fontFiles(regularCyrillic, regularLatin),
    'Nunito ExtraBold': fontFiles(boldCyrillic, boldLatin),
  },
  sources: {
    [BASEMAP]: { type: 'raster', tiles: [tileUrl], tileSize: 256, maxzoom: 19 },
  },
  layers: [{ id: BASEMAP, type: 'raster', source: BASEMAP }],
};
