// Поиск адреса и выбор точек А и Б на телефоне.
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

test('ввожу адрес, получаю подсказки, выбираю точку Б', async ({ page }) => {
  const server = await mockServer(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Куда', exact: true }).click();
  const box = page.getByRole('searchbox', { name: 'Куда: адрес или место' });
  await expect(box).toBeFocused();
  // Шрифт поля от 16 px: iPhone не увеличивает страницу при вводе.
  expect(
    await box.evaluate((el) => parseFloat(getComputedStyle(el).fontSize)),
  ).toBeGreaterThanOrEqual(16);
  await box.pressSequentially('аура', { delay: 40 });
  const suggestion = page.getByRole('button', { name: /Аура.*Военная улица, 5/ });
  await expect(suggestion).toBeVisible();
  // Пауза после ввода: один запрос на всё слово, не по букве.
  expect(server.searchQueries()).toEqual(['аура']);
  await noAxeViolations(page);
  await suggestion.click();
  await expect(page).toHaveURL(/#\/$/);
  await expect(page.getByRole('button', { name: 'Куда: Аура' })).toBeVisible();
  await expect(page.getByRole('img', { name: 'Точка Б: Аура' })).toBeAttached();
  await noAxeViolations(page);
});

test('«Назад» закрывает поиск, точки не теряются', async ({ page }) => {
  await mockServer(page);
  await page.goto('/#/search/from');
  await page.getByRole('searchbox').fill('цирк');
  await page.getByRole('button', { name: /Цирк/ }).click();
  await page.getByRole('button', { name: 'Куда', exact: true }).click();
  await page.getByRole('button', { name: 'Назад' }).click();
  await expect(page.getByRole('button', { name: 'Откуда: Цирк' })).toBeVisible();
});

test('выбор точки на карте: булавка, адрес, «Выбрать эту точку»', async ({ page }) => {
  await mockServer(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Выбрать на карте' }).click();
  await expect(page.getByText('Выберите точку Б')).toBeVisible();
  await expect(page.getByText('Красный проспект, 25/1')).toBeVisible();
  await noAxeViolations(page);
  await page.getByRole('button', { name: 'Выбрать эту точку' }).click();
  await expect(page.getByRole('button', { name: 'Куда: Красный проспект, 25/1' })).toBeVisible();
});

test('поиск недоступен: понятное сообщение, точку можно выбрать на карте', async ({ page }) => {
  await mockServer(page, { searchDown: true });
  await page.goto('/#/search/to');
  await page.getByRole('searchbox').fill('аура');
  await expect(page.getByRole('alert')).toContainText('Поиск адресов сейчас не работает');
  await expect(page.getByRole('button', { name: 'Выбрать на карте' })).toBeVisible();
});

test('медленная сеть: видно «Ищем…», потом подсказки', async ({ page }) => {
  await mockServer(page, { searchDelayMs: 1500 });
  await page.goto('/#/search/to');
  await page.getByRole('searchbox').fill('аура');
  await expect(page.getByText('Ищем…')).toBeVisible();
  await expect(page.getByRole('button', { name: /Аура/ })).toBeVisible();
});
