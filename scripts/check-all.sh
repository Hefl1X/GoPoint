#!/usr/bin/env bash
# Все проверки проекта одной командой: bash scripts/check-all.sh
# Без e2e (быстрее): bash scripts/check-all.sh --fast
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
fast=0
[ "${1:-}" = "--fast" ] && fast=1

step() { printf '\n== %s\n' "$1"; }

step "Сервер: зависимости"
cd "$root/server"
uv sync --locked --quiet

step "Сервер: стиль (ruff)"
uv run ruff check app tests tools
uv run ruff format --check app tests tools

step "Сервер: типы (mypy strict)"
uv run mypy

step "Сервер: границы модулей (import-linter)"
uv run lint-imports

step "Сервер: тесты (pytest)"
uv run pytest

step "Поиск адресов: вырезание города из выгрузки Photon"
uv run ruff check "$root/photon"
uv run ruff format --check "$root/photon"
(cd "$root/photon" && python3 -m unittest -q)

step "Контракт API: типы сайта соответствуют серверу"
uv run python -m app.openapi_export "$root/web/src/adapters/api/openapi.json"
cd "$root/web"
[ -d node_modules ] || npm ci
npm run --silent api:types >/dev/null
if ! git -C "$root" diff --quiet -- web/src/adapters/api/openapi.json web/src/adapters/api/schema.d.ts; then
  echo "Контракт API изменился: файлы openapi.json и schema.d.ts обновлены, закоммитьте их."
  git -C "$root" diff --stat -- web/src/adapters/api/
  [ -n "${CI:-}" ] && exit 1
fi

step "Сайт: форматирование, линтер, типы"
npm run --silent format:check
npm run --silent lint
npm run --silent typecheck

step "Сайт: тесты (vitest)"
npm run --silent test

step "Сайт: сборка"
npm run --silent build >/dev/null

if [ "$fast" -eq 0 ]; then
  step "Сайт: e2e в размерах телефона и доступность (Playwright, axe)"
  npm run --silent e2e
fi

printf '\nВсе проверки пройдены.\n'
