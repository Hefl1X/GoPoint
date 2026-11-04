// Адрес стиля карты. По умолчанию OpenFreeMap (условия: docs/LICENSES.md),
// заменить можно переменной VITE_MAP_STYLE_URL при сборке.
export const STYLE_URL: string =
  (import.meta.env.VITE_MAP_STYLE_URL as string | undefined) ??
  'https://tiles.openfreemap.org/styles/positron';
