// Иконки GoPoint из образца docs/design/AppIcon.dc.html (булавка с символом доступности).
// Запуск (один раз, файлы лежат в public/): node scripts/make-icons.mjs
// Рисует SVG браузером Playwright (уже стоит для e2e), новых зависимостей не нужно.
import { chromium } from '@playwright/test';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const out = (name) => fileURLToPath(new URL(`../public/${name}`, import.meta.url));

const PIN = `<ellipse cx="256" cy="440" rx="92" ry="14" fill="#ffffff" fill-opacity="0.3"/>
<polygon points="162,262 350,262 256,432" fill="#ffffff"/>
<circle cx="256" cy="214" r="106" fill="#ffffff"/>
<circle cx="260" cy="166" r="14" fill="#0f6b5c"/>
<path d="M260 188V226H298L316 262M238 206A40 40 0 1 0 292 270" fill="none" stroke="#0f6b5c" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/>`;

// Обычная иконка: скруглённый квадрат. Maskable и apple-touch: квадрат во всю площадь
// (система сама скругляет), булавка лежит в центральных 80 %.
const rounded = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="112" fill="#0f6b5c"/>${PIN}</svg>`;
const square = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" fill="#0f6b5c"/>${PIN}</svg>`;

writeFileSync(out('favicon.svg'), rounded + '\n');

const files = [
  ['icons/icon-192.png', rounded, 192],
  ['icons/icon-512.png', rounded, 512],
  ['icons/maskable-512.png', square, 512],
  ['icons/apple-touch-icon-180.png', square, 180],
  ['icons/favicon-32.png', rounded, 32],
];

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });
for (const [name, svg, size] of files) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(
    `<html><body style="margin:0;background:transparent">${svg.replace('<svg ', `<svg width="${size}" height="${size}" `)}</body></html>`,
  );
  await page.screenshot({
    path: out(name),
    omitBackground: true,
    clip: { x: 0, y: 0, width: size, height: size },
  });
}
await browser.close();
console.log('Иконки записаны в public/');
