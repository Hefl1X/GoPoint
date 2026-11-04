import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

test('страница открывается и называется GoPoint', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle('GoPoint');
  await expect(page.getByRole('heading', { level: 1, name: 'GoPoint' })).toBeVisible();
});

test('нет нарушений доступности (axe, WCAG 2.2 AA)', async ({ page }) => {
  await page.goto('/');
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze();
  expect(results.violations).toEqual([]);
});

test('нет горизонтальной прокрутки на узком экране', async ({ page }) => {
  await page.goto('/');
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
});
