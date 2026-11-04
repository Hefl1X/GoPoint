import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { mockServer } from './fixtures';

const WCAG = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

async function noAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(WCAG)
    // Внутренности холста карты MapLibre axe не проверяет осмысленно.
    .exclude('.maplibregl-canvas-container')
    .analyze();
  expect(results.violations).toEqual([]);
}

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
}

test('главный экран: карта, число машин, подпись OpenStreetMap', async ({ page }) => {
  await mockServer(page);
  await page.goto('/');
  await expect(page).toHaveTitle('GoPoint');
  await expect(page.getByText('На линии сейчас: 1 низкопольная машина')).toBeVisible();
  await expect(page.getByTestId('map-maplibre')).toBeVisible();
  await expect(page.locator('.map-attribution')).toContainText('© OpenStreetMap contributors');
  // Карта на весь экран: меню и панель лежат поверх неё.
  const box = await page.getByTestId('map-maplibre').boundingBox();
  const viewport = page.viewportSize();
  expect(box?.height).toBe(viewport?.height);
  await expect(page.getByRole('button', { name: 'Моё местоположение' })).toHaveCount(1);
  await expect(page.getByRole('navigation', { name: 'Разделы' })).toBeVisible();
  await noHorizontalScroll(page);
  await noAxeViolations(page);
});

test('панель сворачивается движением вниз и открывает карту', async ({ page }) => {
  await mockServer(page);
  await page.goto('/');
  await expect(page.getByText('На линии сейчас: 1 низкопольная машина')).toBeVisible();
  const grip = page.getByRole('button', { name: 'Свернуть панель' });
  const box = await grip.boundingBox();
  if (!box) throw new Error('нет ручки панели');
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + 60, { steps: 5 });
  await page.mouse.move(x, y + 150, { steps: 5 });
  await page.mouse.up();
  const expand = page.getByRole('button', { name: 'Развернуть панель' });
  await expect(expand).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByText('На линии сейчас: 1 низкопольная машина')).toBeHidden();
  await noAxeViolations(page);
  await expand.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByText('На линии сейчас: 1 низкопольная машина')).toBeVisible();
});

test('без WebGL (список вместо карты) машины выбираются с клавиатуры', async ({ page }) => {
  await mockServer(page);
  await page.goto('/?map=list');
  const vehicle = page.getByRole('button', { name: 'Автобус 3, низкий пол' });
  await vehicle.focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/#\/vehicle\/bus-3-1$/);
  await expect(page.getByRole('heading', { name: 'Автобус 3' })).toBeVisible();
  await expect(page.getByText('в сторону Северный')).toBeVisible();
  await expect(page.getByText('Цирк')).toBeVisible();
  await noAxeViolations(page);
  await page.getByRole('button', { name: 'Закрыть' }).click();
  await expect(page).toHaveURL(/#\/$/);
});

test('«Транспорт»: список, маршрут, «Назад»', async ({ page }) => {
  await mockServer(page);
  await page.goto('/?map=list');
  await page.getByRole('link', { name: 'Транспорт' }).click();
  await expect(page.getByRole('heading', { name: 'Транспорт сейчас' })).toBeVisible();
  // Трамвая 13 нет: низкопольных на нём сейчас нет.
  await expect(page.getByText('Трамвай 13')).toHaveCount(0);
  await noHorizontalScroll(page);
  await noAxeViolations(page);
  await page.getByRole('link', { name: /Автобус 3/ }).click();
  await expect(page.getByRole('heading', { name: 'Автобус 3' })).toBeVisible();
  await expect(page.getByText('едет к «Цирк»')).toBeVisible();
  await noAxeViolations(page);
  await page.getByRole('button', { name: 'Назад' }).click();
  await expect(page.getByRole('heading', { name: 'Транспорт сейчас' })).toBeVisible();
});

test('настройка «Низкопольный транспорт»: клавиатура, память, другой набор машин', async ({
  page,
}) => {
  await mockServer(page);
  await page.goto('/?map=list#/settings');
  const toggle = page.getByRole('switch', { name: 'Низкопольный транспорт' });
  await expect(toggle).toHaveAttribute('aria-checked', 'true');
  await noAxeViolations(page);
  await toggle.focus();
  await page.keyboard.press('Space');
  await expect(toggle).toHaveAttribute('aria-checked', 'false');
  await page.reload();
  await expect(page.getByRole('switch', { name: 'Низкопольный транспорт' })).toHaveAttribute(
    'aria-checked',
    'false',
  );
  await page.getByRole('link', { name: 'Карта' }).click();
  await expect(page.getByText('На линии сейчас: 2 машины')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Автобус 3, не низкий пол' })).toBeVisible();
});

test('«О приложении»: источники и подпись OpenStreetMap', async ({ page }) => {
  await mockServer(page);
  await page.goto('/?map=list#/about');
  await expect(page.getByRole('heading', { name: 'О приложении' })).toBeVisible();
  await expect(page.getByText(/ЦУГАЭТ/)).toBeVisible();
  await expect(page.getByText(/© OpenStreetMap contributors/)).toBeVisible();
  await expect(page.getByText('GoPoint · Версия 0.1.0')).toBeVisible();
  await noAxeViolations(page);
});

test('нет сети: понятное сообщение, интерфейс не ломается', async ({ page }) => {
  await mockServer(page, { failLive: true });
  await page.goto('/?map=list');
  await expect(page.getByText('Нет подключения к интернету')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole('button', { name: 'Повторить' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Разделы' })).toBeVisible();
  await noAxeViolations(page);
});

test('медленная сеть: видна загрузка, потом данные', async ({ page }) => {
  await mockServer(page, { vehiclesDelayMs: 2_000 });
  await page.goto('/?map=list');
  await expect(page.getByText('Загружаем…')).toBeVisible();
  await expect(page.getByText('На линии сейчас: 1 низкопольная машина')).toBeVisible({
    timeout: 10_000,
  });
});

test('в интерфейсе нет слов про способ отслеживания', async ({ page }) => {
  await mockServer(page);
  for (const hash of [
    '',
    '#/transport',
    '#/transport/bus-3',
    '#/settings',
    '#/about',
    '#/vehicle/bus-3-1',
  ]) {
    await page.goto(`/?map=list${hash}`);
    await page.waitForLoadState('networkidle');
    const text = await page.locator('body').innerText();
    expect(text).not.toMatch(/GPS|обновлено|по плану|по расписанию|спутник/i);
  }
});
