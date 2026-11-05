/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

// В разработке запросы /api уходят на сервер (адрес берётся из окружения,
// в клиенте адрес сервера не зашит: сайт всегда ходит на тот же адрес, что и сам).
const apiTarget = process.env.GOPOINT_API_PROXY ?? 'http://127.0.0.1:8000';

const GREEN = '#0f6b5c';

/**
 * Заставка из index.html видна сразу, не дожидаясь стилей сайта: ссылку на стили и скрипт
 * сайта переносим в конец страницы (стили по-прежнему грузятся до запуска скрипта, поэтому
 * сайт не мигает без оформления). На медленной сети заставка появляется на ~0,7 с раньше.
 */
function splashFirst(): Plugin {
  return {
    name: 'gopoint-splash-first',
    transformIndexHtml: {
      order: 'post',
      handler(html) {
        const moved: string[] = [];
        const head = html.replace(
          /\s*<(link rel="stylesheet"[^>]*|script type="module"[^>]*><\/script)>/g,
          (tag) => {
            moved.push(tag.trim());
            return '';
          },
        );
        // Стили раньше скрипта: скрипт ждёт загрузки стилей перед запуском.
        moved.sort((a, b) => Number(a.startsWith('<script')) - Number(b.startsWith('<script')));
        return head.replace('</body>', `${moved.join('\n')}\n</body>`);
      },
    },
  };
}

export default defineConfig({
  plugins: [
    react(),
    splashFirst(),
    // PWA: манифест и service worker (docs/DESIGN.md, «Иконка и PWA»).
    // Без сети работают оболочка сайта и справочники (список маршрутов, остановки
    // открытых маршрутов). Положения машин и маршруты без сети не берутся: сайт
    // показывает «Нет подключения», а машины из сохранённого ответа скрывает (shared/queries.ts).
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: false,
      includeAssets: ['favicon.svg', 'icons/favicon-32.png', 'icons/apple-touch-icon-180.png'],
      manifest: {
        id: '/',
        name: 'GoPoint · Новосибирск',
        short_name: 'GoPoint',
        description: 'Транспорт Новосибирска на линии сейчас и маршрут по низкопольным машинам',
        lang: 'ru',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'portrait',
        theme_color: GREEN,
        background_color: GREEN,
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: '/icons/maskable-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        // Файл карты MapLibre около 1 МБ: тоже сохраняется для работы без сети.
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/health/],
        cleanupOutdatedCaches: true,
        runtimeCaching: [
          {
            // Справочники: настройки сервера, список маршрутов, остановки и линия маршрута.
            // Сначала сеть; без ответа за 6 с или без сети берётся сохранённый ответ.
            urlPattern: /\/api\/v1\/(meta$|live\/routes(\/[^/?]+)?(\?.*)?$)/,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'gopoint-reference',
              networkTimeoutSeconds: 6,
              expiration: { maxEntries: 400, maxAgeSeconds: 7 * 24 * 3600 },
              cacheableResponse: { statuses: [200] },
            },
          },
        ],
      },
    }),
  ],
  server: {
    host: true,
    proxy: { '/api': apiTarget },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['src/test-setup.ts'],
  },
});
