# HANDOFF: состояние работы

Обновлено: 2026-11-04.

## Цель
Демо GoPoint на Mac владельца: маршрут по Новосибирску по машинам на линии сейчас,
с настройкой «Низкопольный транспорт». Порядок задач: `PROMPTS.md`.

## Сделано
- **Запрос 0.** Mac проверен (`scripts/check-mac.sh` пишет «всё готово»): Apple Silicon, Git, Node 24,
  uv + Python 3.12, Docker Desktop (7,7 ГБ памяти). Репозиторий git, первый коммит с документами.
- **Запрос 1 (каркас).**
  - `server/`: FastAPI, типы предметной области (`app/domain/models.py`), порты `TransitFeed`,
    `WalkPlanner`, `Geocoder` (`app/ports`), пустые папки адаптеров, единый формат ошибок,
    все адреса раздела 9 в контракте. Работают `/health`, `/api/v1/health`, `/api/v1/meta`;
    остальные отвечают 501 «Эта функция ещё в разработке.». ruff, mypy strict, import-linter, pytest.
  - `web/`: Vite + React 19 + TypeScript strict, TanStack Query, zod, клиент API с проверкой ответов,
    типы из OpenAPI (`src/adapters/api/schema.d.ts`), тексты в `src/shared/ru.ts` с тестом на
    запрещённые слова, ESLint с запретом карт и сети вне `adapters/`, Vitest, Playwright 360×640
    и 390×844 с axe. Страница пока пустая (заголовок GoPoint).
  - `docker-compose.yml`: `server` (внутренняя сеть) и `caddy` (сайт + прокси `/api`, наружу 8080/8443).
  - `scripts/run-demo.sh`, `stop-demo.sh`, `check-all.sh`, `check-mac.sh`; CI `.github/workflows/ci.yml`.
  - Документы: `DECISIONS.md`, `LICENSES.md`, `DATA_QUALITY.md`, `README.md`, `.env.example`.

## В работе
Ничего не начато.

## Следующие шаги
1. **Запрос 2**: адаптер ЦУГАЭТ в `server/app/adapters/tsugaet/` (разбор из `data/tsugaet/nskgortrans.py`,
   тесты на `samples/`), фоновый опрос, кэш, `/live/*`, адаптер `fake/`, первый `DATA_QUALITY.md`.
   Первым делом `python3 data/tsugaet/nskgortrans.py check`.
2. Запрос 3: карта MapLibre, экраны, нижняя панель, шрифт Nunito, цвета из DESIGN.md.

## Вопросы к владельцу
- Подтвердить порог свежести положения машины: 5 минут (`STALE_SECONDS`=300).
- Разрешение ЦУГАЭТ и `terms_of_use.docx`: пока нет, сервис в общий доступ не публикуется.
- GitHub: репозитория пока нет, CI заработает после того, как владелец создаст репозиторий
  и разрешит выложить туда код (это публикация, решение владельца; репозиторий можно сделать закрытым).

## Известные ошибки и ограничения
- Страница `/api/docs` (Swagger) подгружает оформление с cdn.jsdelivr.net: без интернета не откроется.
  Для демо неважно.
- Предупреждение в тестах сервера: Starlette советует `httpx2` для тестового клиента. На работу не влияет;
  пересмотреть при обновлении FastAPI.
- Проверка «контракт API актуален» в `check-all.sh` сравнивает с последним коммитом: локально только
  предупреждает, в CI падает.
- Границы города пока прямоугольник (см. DECISIONS.md).

## Как запустить и проверить
- Демо: `bash scripts/run-demo.sh` → `http://localhost:8080`, описание API `http://localhost:8080/api/docs`,
  на телефоне адрес из вывода скрипта.
- Проверки: `bash scripts/check-all.sh` (без e2e: `--fast`).
- Только сервер для разработки: `cd server && uv run uvicorn app.main:app --reload`;
  только сайт: `cd web && npm run dev` (запросы `/api` уходят на 127.0.0.1:8000).
- Изменился API на сервере → `uv run python -m app.openapi_export ../web/src/adapters/api/openapi.json`
  в `server/`, затем `npm run api:types` в `web/` (или просто `check-all.sh`).
