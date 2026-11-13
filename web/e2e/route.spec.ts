// Главный путь: открыл сайт, поставил А и Б, увидел время и шаги. Плюс состояния маршрута.
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { mockServer } from './fixtures';

const WCAG = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

async function noAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(WCAG)
    .exclude('.maplibregl-canvas-container')
    .analyze();
  expect(results.violations).toEqual([]);
}

async function choose(page: Page, field: 'Откуда' | 'Куда', query: string, option: RegExp) {
  await page.getByRole('button', { name: field, exact: true }).click();
  await page.getByRole('searchbox').pressSequentially(query, { delay: 30 });
  await page.getByRole('button', { name: option }).click();
}

async function setPoints(page: Page) {
  await page.goto('/');
  await choose(page, 'Откуда', 'аура', /Аура/);
  await choose(page, 'Куда', 'красный', /Красный проспект/);
}

test('открыл сайт, поставил А и Б, увидел время и шаги', async ({ page }) => {
  await mockServer(page);
  await setPoints(page);
  const route = page.getByRole('region', { name: 'Маршрут', exact: true });
  await expect(route.getByRole('heading', { name: /^Автобус 3 · (9|10) мин$/ })).toBeVisible();
  await expect(route.getByText(/^Приедете в \d\d:\d\d · 26 минут в пути/)).toBeVisible();
  await expect(route.getByText('Построен только по низкопольным рейсам')).toBeVisible();
  await expect(route.getByRole('img', { name: /^Шкала времени/ })).toBeVisible();
  await expect(route.getByRole('listitem')).toHaveCount(3);
  await expect(route.getByText(/Время ориентировочное/)).toBeAttached();
  // Нет слов про способ отслеживания и время обновления.
  const text = (await page.locator('body').innerText()).toLowerCase();
  for (const word of ['gps', 'обновлено', 'по плану', 'по расписанию']) {
    expect(text).not.toContain(word);
  }
  // Цели нажатия от 44 px. Ручка панели ниже (34 px), но во всю ширину экрана.
  const sizes = await page
    .locator('button:visible:not(.sheet__grip)')
    .evaluateAll((els) => els.map((el) => el.getBoundingClientRect().height));
  expect(Math.min(...sizes)).toBeGreaterThanOrEqual(44);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
  await noAxeViolations(page);
});

test('настройка выключена: любой транспорт и пометка «не низкий пол»', async ({ page }) => {
  await mockServer(page);
  await page.goto('/#/settings');
  const toggle = page.getByRole('switch', { name: 'Низкопольный транспорт' });
  await expect(toggle).toHaveAttribute('aria-checked', 'true');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-checked', 'false');
  await page.getByRole('link', { name: 'Карта' }).click();
  await choose(page, 'Откуда', 'аура', /Аура/);
  await choose(page, 'Куда', 'красный', /Красный проспект/);
  const route = page.getByRole('region', { name: 'Маршрут', exact: true });
  await expect(route.getByText('Любой транспорт: часть рейсов не низкопольная')).toBeVisible();
  await expect(route.getByRole('listitem').nth(1)).toContainText('не низкий пол');
  await noAxeViolations(page);
});

test('транспорта нет: серый блок, без пешего маршрута', async ({ page }) => {
  await mockServer(page, { noTransit: true });
  await setPoints(page);
  await expect(page.getByText('Транспорта сейчас нет').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Обновить' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Выбрать другие точки' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Маршрут', exact: true })).toHaveCount(0);
  await noAxeViolations(page);
});

test('медленный расчёт: «Ищем маршрут…», потом маршрут', async ({ page }) => {
  await mockServer(page, { routeDelayMs: 1500 });
  await setPoints(page);
  await expect(page.getByText('Ищем маршрут…')).toBeVisible();
  await noAxeViolations(page);
  await expect(page.getByRole('heading', { name: /^Автобус 3 · / })).toBeVisible();
});

test('машина встала: «Маршрут изменился», решает человек', async ({ page }) => {
  await mockServer(page, { vehicleStopped: true });
  await setPoints(page);
  await expect(page.getByText('Маршрут изменился')).toBeVisible();
  await expect(page.getByText('Автобус 3 стоит на месте уже 9 минут.')).toBeVisible();
  await expect(page.getByRole('heading', { name: /^Автобус 3 · / })).toBeVisible();
  await noAxeViolations(page);
  await page.getByRole('button', { name: 'Принять новый' }).click();
  await expect(page.getByRole('heading', { name: /^Автобус 36 · / })).toBeVisible();
  await expect(page.getByText('Маршрут изменился')).toHaveCount(0);
});

test('точки рядом: карточки «транспорт» и «Пешком», выбирает человек', async ({ page }) => {
  await mockServer(page, { walkOption: true });
  await setPoints(page);
  const group = page.getByRole('group', { name: 'Варианты маршрута' });
  await expect(group.getByRole('button')).toHaveCount(2);
  const walk = group.getByRole('button', { name: /Пешком/ });
  await expect(walk).toContainText('5 мин · ≈ 210 м');
  await expect(page.getByRole('heading', { name: /^Автобус 3/ })).toBeVisible();
  await walk.click();
  await expect(page.getByRole('heading', { name: 'Пешком · 5 мин' })).toBeVisible();
  await expect(walk).toHaveAttribute('aria-pressed', 'true');
  const box = await walk.boundingBox();
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
  await noAxeViolations(page);
});
