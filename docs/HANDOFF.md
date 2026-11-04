# HANDOFF: состояние работы

Обновлено: 2026-11-04 (после запроса 2).

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

- **Запрос 2 (данные ЦУГАЭТ).**
  - `server/app/adapters/tsugaet/parse.py`: чистый разбор listmarsh, markers, trasses (тесты на образцах:
    ramp, time_nav в UTC, rasp через полночь, отстой и обед, битая запись, тип 13/13).
  - `server/app/adapters/tsugaet/feed.py`: httpx, пачки по 6, пауза 0,5 с, User-Agent, ошибки → `TransitFeedError`.
  - `server/app/adapters/fake/feed.py`: те же образцы без сети (`GOPOINT_TRANSIT_FEED=fake`).
  - `server/app/services/live_snapshot.py`: один снимок на всех, опрос раз в 30 с только при активности
    за 2 мин, маршруты и линии на сутки, прошлый снимок при сбое (по пачкам).
  - `server/app/domain/live.py`: кого показывать (на линии, свежее 5 мин, при lowFloorOnly только yes).
  - Адреса `/api/v1/live/vehicles` (bbox, lowFloorOnly), `/live/routes` (type, счётчики), `/live/routes/{id}`
    (остановки, линия, машины по направлениям). Служебное поле `diagnostics` (время снимка).
  - Отчёт `docs/DATA_QUALITY.md` (замер `server/tools/data_quality.py`), сетевой тест `uv run pytest -m network`.
  - GitHub: закрытый репозиторий `Hefl1X/GoPoint`, CI зелёный.

## В работе
Ничего не начато.

## Следующие шаги
1. **Запрос 3**: карта MapLibre за портом MapView, экраны Start, LiveRoutes, LiveRoute, VehicleCard, Settings,
   «О приложении», нижняя панель, шрифт Nunito, цвета из DESIGN.md. Сайт обращается к `/live/*`;
   пока сервер ждёт первый опрос (около 8 с после простоя), сайт показывает загрузку.
2. Запрос 6 учтёт выводы DATA_QUALITY.md: положение отстаёт на 30–60 с, `segment_order = 0` это «неизвестно»,
   машины далеко от линии не брать.

## Вопросы к владельцу
- Маршрутки: включать ли в приложение? Сейчас выключены. По замеру низкопольных среди них 3 из 134.
- Подтвердить порог свежести положения машины: 5 минут (`STALE_SECONDS`=300). По замеру так отсекается 4% машин.
- Разрешение ЦУГАЭТ и `terms_of_use.docx`: пока нет, сервис в общий доступ не публикуется.

## Известные ошибки и ограничения
- Страница `/api/docs` (Swagger) подгружает оформление с cdn.jsdelivr.net: без интернета не откроется.
  Для демо неважно.
- Предупреждение в тестах сервера: Starlette советует `httpx2` для тестового клиента. На работу не влияет;
  пересмотреть при обновлении FastAPI.
- Проверка «контракт API актуален» в `check-all.sh` сравнивает с последним коммитом: локально только
  предупреждает, в CI падает.
- Границы города пока прямоугольник (см. DECISIONS.md).
- Первый запрос к `/live/*` после 2 минут тишины ждёт опрос ЦУГАЭТ около 8 с.
- `/live/vehicles/{id}`, `/live/stops/{id}/arrivals`, `/route`, `/search` пока отвечают 501 (запросы 4 и 6).
- У 8 маршрутов (трамваи 2 и 8, шесть маршруток) обратное направление пустое: в `/live/routes/{id}`
  приходит одно направление.
- Работа «прошлого снимка» при отключённом интернете проверена автоматическими тестами,
  вручную с выключенным интернетом не проверялась.

## Как запустить и проверить
- Демо: `bash scripts/run-demo.sh` → `http://localhost:8080`, описание API `http://localhost:8080/api/docs`,
  на телефоне адрес из вывода скрипта.
- Проверки: `bash scripts/check-all.sh` (без e2e: `--fast`).
- Только сервер для разработки: `cd server && uv run uvicorn app.main:app --reload`;
  только сайт: `cd web && npm run dev` (запросы `/api` уходят на 127.0.0.1:8000).
- Изменился API на сервере → `uv run python -m app.openapi_export ../web/src/adapters/api/openapi.json`
  в `server/`, затем `npm run api:types` в `web/` (или просто `check-all.sh`).
