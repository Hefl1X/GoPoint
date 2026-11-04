# Лицензии и условия внешних сервисов

Для каждого внешнего сервиса: ссылка на условия, дата проверки, главные ограничения.
Сервисы, которые ещё не подключены, отмечены «не проверено»: условия читаются в задаче, где сервис подключается.

| Сервис | Где используется | Условия | Проверено | Главные ограничения |
|---|---|---|---|---|
| ЦУГАЭТ, map.nskgortrans.ru | данные о транспорте (запрос 2) | официальных условий API нет; `terms_of_use.docx` и письменное разрешение оформляет владелец | не проверено | пока нет письменного разрешения: нагрузка минимальная, сервис не публикуется в общий доступ; источник указывается в «О приложении» |
| OpenStreetMap | улицы для пеших участков, подложка карты | https://www.openstreetmap.org/copyright (ODbL) | не проверено | подпись «© OpenStreetMap contributors» на карте и в «О приложении» обязательна |
| OpenFreeMap | тайлы карты (стиль positron) | https://openfreemap.org/tos/ | 2026-11-04 | бесплатно, без ключа и регистрации, без cookie, ограничений на число запросов нет; без гарантий, может прекратить работу без предупреждения; запросы идут через Cloudflare; запрещён массовый автоматический сбор (скачивание для работы без сети не больше 3000 тайлов / 50 МБ). Подпись «OpenFreeMap © OpenMapTiles Data from OpenStreetMap» MapLibre ставит сам |
| localhost.run | временный HTTPS-туннель для проверки на телефоне (`scripts/run-tunnel.sh`) | https://localhost.run (документацию прочитать не удалось: сайт не открылся моему инструменту; проверено на деле) | 2026-11-04 | бесплатно без регистрации; адрес `*.lhr.life` случайный и меняется; весь трафик сайта идёт через их сервер; только для проверок, не для постоянной работы |
| Cloudflare Quick Tunnel | пробовали для туннеля, не используется | https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/ | 2026-11-04 | из сети владельца не подключается (соединение с Cloudflare обрывается) |
| Photon (публичный сервер komoot) | поиск адресов и адрес точки на карте (`server/app/adapters/photon`) | https://photon.komoot.io , https://github.com/komoot/photon (Apache-2.0, версия 1.3.0) | 2026-11-04 | пользоваться можно, пока число запросов «в разумных пределах»; при большой нагрузке ограничат или заблокируют; работа не гарантируется, условия могут измениться без предупреждения; при большой нагрузке советуют свой сервер. Данные OpenStreetMap: подпись «Поиск адресов: © OpenStreetMap contributors» под подсказками и в «О приложении» |
| Nominatim (OpenStreetMap) | только разовая ручная проверка качества поиска (`server/tools/geocoder_quality.py`), в работе сайта не используется | https://operations.osmfoundation.org/policies/nominatim/ | 2026-11-04 | не чаще 1 запроса в секунду, понятный User-Agent, без массовых выгрузок; 30 запросов раз в день допустимы |
| OpenTripPlanner | пешие участки (запрос 5) | LGPL-3.0, https://www.opentripplanner.org | не проверено | используется как отдельный контейнер без изменений |
| Copernicus DEM | рельеф (запрос 5) | https://spacedata.copernicus.eu | не проверено | указать источник |

## Библиотеки проекта

Все зависимости открытые (MIT, BSD, Apache-2.0, ISC). Проверка 2026-11-04 по файлам лицензий пакетов:

| Пакет | Лицензия | Зачем |
|---|---|---|
| FastAPI, pydantic, pydantic-settings, httpx, uvicorn | MIT / BSD-3 | сервер |
| pytest, pytest-asyncio, ruff, mypy, import-linter | MIT / Apache-2.0 / BSD-2 | проверки сервера |
| React, react-dom | MIT | интерфейс |
| @tanstack/react-query | MIT | запросы к серверу, обновление раз в 30 с |
| zod | MIT | проверка ответов сервера |
| Vite, @vitejs/plugin-react, Vitest | MIT | сборка и тесты сайта |
| TypeScript, Playwright | Apache-2.0 | типы, e2e-тесты |
| ESLint, typescript-eslint, eslint-plugin-react-hooks, eslint-plugin-jsx-a11y, Prettier | MIT | проверки кода сайта |
| @axe-core/playwright | MPL-2.0 | автоматическая проверка доступности (только в тестах) |
| openapi-typescript | MIT | генерация типов сайта из контракта API |
| maplibre-gl | BSD-3-Clause | карта |
| @fontsource/nunito | OFL-1.1 (шрифт Nunito) | шрифт, файлы лежат в сборке сайта |
| Caddy | Apache-2.0 | раздача сайта и HTTPS |
