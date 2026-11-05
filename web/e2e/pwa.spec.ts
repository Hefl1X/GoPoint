// PWA: манифест, иконки, работа без сети. Здесь service worker включён, поэтому
// сервер подменяется на уровне контекста браузера (видит и запросы service worker).
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type BrowserContext } from '@playwright/test';

test.use({ serviceWorkers: 'allow' });

const point = (lat: number, lon: number) => ({ lat, lon });
const stop = (id: string, name: string) => ({ id, name, point: point(55.03, 82.92) });
const bus = {
  id: 'bus-3-1',
  lineId: 'bus-3',
  type: 'bus',
  number: '3',
  direction: 'A',
  point: point(55.03, 82.92),
  azimuth: 90,
  speedKmh: 20,
  lowFloor: 'yes',
  positionObservedAt: new Date().toISOString(),
};

async function mockServer(context: BrowserContext) {
  await context.route('https://tiles.openfreemap.org/**', (route) => route.abort());
  await context.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    const diagnostics = { fetchedAt: new Date().toISOString(), complete: true };
    if (path === '/meta') {
      return route.fulfill({
        json: {
          appName: 'GoPoint',
          version: '0.1.0',
          cityBounds: { southWest: point(54.8, 82.7), northEast: point(55.2, 83.2) },
          refreshIntervalS: 30,
          lowFloorOnlyDefault: true,
          staleSeconds: 300,
        },
      });
    }
    if (path === '/live/vehicles') return route.fulfill({ json: { vehicles: [bus], diagnostics } });
    if (path === '/live/routes') {
      return route.fulfill({
        json: {
          lines: [
            {
              line: { id: 'bus-3', type: 'bus', number: '3', title: 'Вокзал — Северный' },
              vehiclesOnLine: 1,
            },
          ],
          diagnostics,
        },
      });
    }
    if (path === '/live/routes/bus-3') {
      return route.fulfill({
        json: {
          line: { id: 'bus-3', type: 'bus', number: '3', title: 'Вокзал — Северный' },
          directions: [
            {
              direction: 'A',
              stops: [stop('1', 'Вокзал'), stop('2', 'Цирк'), stop('3', 'Северный')],
              path: [point(55.03, 82.9), point(55.05, 82.92)],
              vehicles: [{ vehicle: bus, nextStopOrder: 1 }],
            },
          ],
          diagnostics,
        },
      });
    }
    return route.fulfill({ status: 404, json: { code: 'NOT_FOUND', message: 'Нет.' } });
  });
}

test('манифест и иконки для установки на экран телефона', async ({ page, request }) => {
  await page.goto('/?map=list');
  const href = await page.locator('link[rel="manifest"]').getAttribute('href');
  expect(href).toBeTruthy();
  const manifest = (await (await request.get(href ?? '')).json()) as {
    short_name: string;
    name: string;
    theme_color: string;
    display: string;
    icons: { src: string; sizes: string; purpose?: string }[];
  };
  expect(manifest.short_name).toBe('GoPoint');
  expect(manifest.name).toBe('GoPoint · Новосибирск');
  expect(manifest.theme_color).toBe('#0f6b5c');
  expect(manifest.display).toBe('standalone');
  expect(manifest.icons.map((i) => i.sizes)).toEqual(['192x192', '512x512', '512x512']);
  expect(manifest.icons.some((i) => i.purpose === 'maskable')).toBe(true);
  for (const src of [
    ...manifest.icons.map((i) => i.src),
    '/icons/apple-touch-icon-180.png',
    '/icons/favicon-32.png',
    '/favicon.svg',
  ]) {
    expect((await request.get(src)).status(), src).toBe(200);
  }
});

test('без сети: сайт открывается, маршруты и остановки видны, машины и маршрут — «Нет подключения»', async ({
  context,
  page,
}) => {
  await mockServer(context);
  await page.goto('/?map=list#/transport');
  await expect(page.getByRole('link', { name: /Автобус 3/ })).toBeVisible();
  // Ждём, пока service worker возьмёт страницу под контроль, и открываем маршрут,
  // чтобы его остановки сохранились.
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });
  await page.reload();
  await expect
    .poll(() => page.evaluate(() => navigator.serviceWorker.controller !== null))
    .toBe(true);
  await page.getByRole('link', { name: /Автобус 3/ }).click();
  await expect(page.getByText('едет к «Цирк»')).toBeVisible();

  // Сервера больше нет: подмена отвечает «нет сети» и на запросы service worker.
  await context.unrouteAll();
  await context.route('**/api/v1/**', (route) => route.abort('internetdisconnected'));
  await context.setOffline(true);
  await page.goto('/?map=list');
  // Оболочка сайта открылась, положения машин без сети не берутся.
  await expect(page.getByRole('navigation', { name: 'Разделы' })).toBeVisible();
  await expect(page.getByText('Нет подключения к интернету').first()).toBeVisible();
  await page.getByRole('link', { name: 'Транспорт' }).click();
  await expect(page.getByRole('link', { name: /Автобус 3/ })).toBeVisible();
  await page.getByRole('link', { name: /Автобус 3/ }).click();
  await expect(page.getByText('Цирк').first()).toBeVisible();
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze();
  expect(results.violations).toEqual([]);
});
