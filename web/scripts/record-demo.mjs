// Запись экрана демо на живых данных (запасной вариант показа, docs/DEMO_CHECKLIST.md, раздел 8).
// Запуск при работающем демо: cd web && node scripts/record-demo.mjs ../docs/demo
import { chromium } from '@playwright/test';
const OUT = process.argv[2];
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
  locale: 'ru-RU',
  timezoneId: 'Asia/Novosibirsk',
  serviceWorkers: 'block',
  recordVideo: { dir: OUT, size: { width: 390, height: 844 } },
});
const page = await context.newPage();
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png` });
const pause = (ms) => page.waitForTimeout(ms);

async function choose(field, q, option) {
  await page
    .getByRole('button', { name: new RegExp('^' + field) })
    .first()
    .click();
  await page.getByRole('searchbox').pressSequentially(q, { delay: 90 });
  await page.getByRole('button', { name: option }).first().click();
}
await page.goto('http://localhost:8080/');
await page.getByText(/На линии сейчас/).waitFor({ timeout: 60000 });
await pause(4000);
await shot('1-start');
await choose('Откуда', 'речной вокзал', /Речной вокзал/);
await choose('Куда', 'галерея новосибирск', /Галерея Новосибирск/);
const route = page.getByRole('region', { name: 'Маршрут', exact: true });
await route.getByText(/^Приедете в/).waitFor({ timeout: 90000 });
await pause(3000);
await shot('2-route');
await page
  .getByRole('region', { name: 'Маршрут', exact: true })
  .getByRole('list')
  .scrollIntoViewIfNeeded();
await pause(2500);
await shot('3-steps');
// Сценарий 3: вокзал → оперный театр, потом настройка «Низкопольный транспорт».
await choose('Откуда', 'новосибирск-главный', /Новосибирск-Главный/);
await choose('Куда', 'оперный театр', /театр оперы и балета/);
await page
  .getByText(/^Приедете в|Транспорта сейчас нет/)
  .first()
  .waitFor({ timeout: 90000 });
await pause(3000);
await shot('4-route-lowfloor');
await page.getByRole('link', { name: 'Настройки' }).click();
await pause(1500);
await page.getByRole('switch', { name: 'Низкопольный транспорт' }).click();
await pause(1500);
await shot('5-settings-off');
await page.getByRole('link', { name: 'Карта' }).click();
await route.getByText(/^Приедете в/).waitFor({ timeout: 90000 });
await pause(3000);
await shot('6-route-any');
await page.getByRole('link', { name: 'Настройки' }).click();
await page.getByRole('switch', { name: 'Низкопольный транспорт' }).click();
// «Транспорт» → маршрут → остановка.
await page.getByRole('link', { name: 'Транспорт' }).click();
await page.getByRole('searchbox').or(page.getByRole('textbox')).first().fill('13');
await pause(1500);
await page
  .getByRole('link', { name: /Трамвай 13/ })
  .first()
  .click();
await pause(2500);
await shot('7-line');
await page
  .getByRole('link', { name: /Остановка «/ })
  .nth(5)
  .click();
await page.getByText(/Ближайший транспорт/).waitFor();
await pause(4000);
await shot('8-stop');
await context.close();
await browser.close();
