import { defineConfig, devices } from '@playwright/test';

// e2e в размерах телефона. Сайт собирается и запускается сам (vite preview).
const port = '4173';

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    locale: 'ru-RU',
    timezoneId: 'Asia/Novosibirsk',
    // Service worker перехватил бы запросы мимо подменённого сервера (page.route).
    // Работа без сети проверяется отдельно: e2e/pwa.spec.ts включает его сам.
    serviceWorkers: 'block',
  },
  projects: [
    {
      name: 'phone-360x640',
      use: { ...devices['Pixel 5'], viewport: { width: 360, height: 640 } },
    },
    {
      name: 'phone-390x844',
      use: { ...devices['Pixel 5'], viewport: { width: 390, height: 844 } },
    },
    {
      // Размер экрана iPhone 15 Pro (телефон владельца).
      name: 'iphone-15-pro-393x852',
      use: { ...devices['Pixel 5'], viewport: { width: 393, height: 852 } },
    },
  ],
  webServer: {
    command: `npm run build && npx vite preview --port ${port} --strictPort --host 127.0.0.1`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
