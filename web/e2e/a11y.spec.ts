// Доступность всех экранов (запрос 9): axe по WCAG 2.2 AA, перестроение на ширине 320 px
// без прокрутки вбок (WCAG 1.4.10), управление с клавиатуры без мыши.
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { mockServer } from './fixtures';

const WCAG = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

async function check(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(WCAG)
    .exclude('.maplibregl-canvas-container')
    .analyze();
  expect(results.violations).toEqual([]);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
}

async function setPoints(page: Page) {
  for (const [field, query, option] of [
    ['Откуда', 'аура', /Аура/],
    ['Куда', 'красный', /Красный проспект/],
  ] as const) {
    await page.getByRole('button', { name: field, exact: true }).click();
    await page.getByRole('searchbox').pressSequentially(query, { delay: 20 });
    await page.getByRole('button', { name: option }).click();
  }
}

test('точка вне Новосибирска: понятное сообщение и выбор другой точки', async ({ page }) => {
  await mockServer(page, {
    routeError: {
      status: 422,
      code: 'OUTSIDE_CITY',
      message: 'Эта точка за пределами Новосибирска.',
    },
  });
  await page.goto('/');
  await setPoints(page);
  await expect(page.getByText(/за пределами Новосибирска|вне Новосибирска/).first()).toBeVisible();
  await check(page);
});

test('нет пути без лестниц: понятное сообщение', async ({ page }) => {
  await mockServer(page, {
    routeError: {
      status: 422,
      code: 'NO_ACCESSIBLE_WALK',
      message: 'До остановки нет пути без лестниц. Выберите точку рядом с улицей.',
    },
  });
  await page.goto('/');
  await setPoints(page);
  await expect(page.getByText(/без лестниц/).first()).toBeVisible();
  await check(page);
});

test('нет доступа к местоположению: объяснение, сайт работает', async ({ page, context }) => {
  await context.clearPermissions();
  await mockServer(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Моё местоположение' }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await check(page);
});

test.describe('ширина 320 px (как при увеличении текста)', () => {
  test.use({ viewport: { width: 320, height: 568 } });

  for (const hash of [
    '#/',
    '#/transport',
    '#/transport/bus-3',
    '#/stop/2',
    '#/vehicle/bus-3-1',
    '#/settings',
    '#/about',
    '#/install',
    '#/search/to',
  ]) {
    test(hash, async ({ page }) => {
      await mockServer(page);
      await page.goto(`/?map=list${hash}`);
      await expect(page.getByRole('navigation', { name: 'Разделы' })).toBeVisible();
      await page.waitForLoadState('networkidle');
      await check(page);
    });
  }
});

test('с клавиатуры: от карты до экрана остановки без мыши', async ({ page }) => {
  await mockServer(page);
  await page.goto('/?map=list#/transport');
  const link = page.getByRole('link', { name: /Автобус 3/ });
  await link.focus();
  await page.keyboard.press('Enter');
  const stop = page.getByRole('link', { name: 'Остановка «Цирк»: что подъезжает' }).first();
  await stop.focus();
  await expect(stop).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Цирк' })).toBeFocused();
  // Фокус виден: у элемента есть рамка фокуса.
  const button = page.getByRole('button', { name: 'Проложить маршрут отсюда' });
  await button.focus();
  const outline = await button.evaluate((el) => getComputedStyle(el).outlineStyle);
  expect(outline).not.toBe('none');
});
