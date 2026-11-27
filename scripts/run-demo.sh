#!/usr/bin/env bash
# Запуск демо GoPoint на этом компьютере одной командой:
#   bash scripts/run-demo.sh
# Остановка: bash scripts/stop-demo.sh
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker не установлен. Установите Docker Desktop с docker.com и запустите снова."
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker не запущен. Откройте Docker Desktop (значок кита), дождитесь,"
  echo "пока он напишет, что работает, и запустите эту команду снова."
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Создан файл настроек .env (из .env.example)."
fi

port="${GOPOINT_HTTP_PORT:-$(grep -E '^GOPOINT_HTTP_PORT=' .env | cut -d= -f2 || true)}"
port="${port:-8080}"

export GOPOINT_RT_DIR="${GOPOINT_RT_DIR:-$PWD/data/otp/demo}"
if [ -z "${GOPOINT_RT_VERSION:-}" ] && [ -f "$GOPOINT_RT_DIR/current" ]; then
  GOPOINT_RT_VERSION="$(cat "$GOPOINT_RT_DIR/current")"
fi
if [ -z "${GOPOINT_RT_VERSION:-}" ]; then
  echo "Транспортное расписание не подготовлено. Запуск без него не строит поездки."
  echo "Выполните один раз: bash scripts/prepare-demo.sh ДАТА-КОНЦА (например 2026-12-20)."
  exit 1
fi
export GOPOINT_RT_VERSION
GOPOINT_RT_DIR="$(cd "$GOPOINT_RT_DIR" && pwd)"
(cd server && uv run --locked python -m tools.demo_release \
  --store "$GOPOINT_RT_DIR" --version "$GOPOINT_RT_VERSION")
compose=(docker compose -f docker-compose.yml -f otp/release/demo.compose.yml)

# Старый проверочный стенд использовал тот же том Photon и мешает открыть базу.
stage8="$(docker ps -q --filter label=com.docker.compose.project=gopoint-stage8)"
if [ -n "$stage8" ]; then
  echo "Останавливаю тестовый stage8, чтобы освободить общую базу поиска."
  docker stop $stage8 >/dev/null
fi

echo "Собираю и запускаю GoPoint (первый раз это может занять несколько минут)..."
"${compose[@]}" up -d --build

echo -n "Жду, пока сервис ответит"
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:${port}/health" >/dev/null 2>&1 && \
    "${compose[@]}" exec -T server python -c '
import json, os, urllib.request
request = urllib.request.Request("http://otp:8080/otp/gtfs/v1",
    data=json.dumps({"query": "{ feeds { feedId version } }"}).encode(),
    headers={"Content-Type": "application/json"})
with urllib.request.urlopen(request, timeout=2) as response:
    feeds = {item["feedId"]: item["version"] for item in json.load(response)["data"]["feeds"]}
version = os.environ["GOPOINT_REALTIME_RELEASE"].rsplit("/", 1)[-1]
assert feeds == {"gopoint-all": version, "gopoint-low": version}
' >/dev/null 2>&1; then
    echo " готово."
    ready=1
    break
  fi
  echo -n "."
  sleep 2
done
if [ "${ready:-0}" != 1 ]; then
  echo
  echo "Сервис не ответил за 2 минуты. Что показывают контейнеры:"
  "${compose[@]}" ps
  echo "Подробности: docker compose logs --tail 50 server otp"
  exit 1
fi

# База поиска адресов собирается отдельно (один раз, около 5 минут).
if ! "${compose[@]}" exec -T photon test -d /data/photon_data >/dev/null 2>&1; then
  echo
  echo "Внимание: база поиска адресов ещё не собрана, подсказки адресов работать не будут."
  echo "Соберите её один раз: bash scripts/build-photon-db.sh"
fi

lan_ip=""
for iface in en0 en1 en2; do
  lan_ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
  [ -n "$lan_ip" ] && break
done

echo
echo "GoPoint запущен."
echo "  На этом компьютере:  http://localhost:${port}"
if [ -n "$lan_ip" ]; then
  echo "  На телефоне:         http://${lan_ip}:${port}   (телефон в той же сети Wi-Fi)"
else
  echo "  Адрес для телефона не найден: компьютер не подключён к Wi-Fi?"
fi
echo "  Описание API:        http://localhost:${port}/api/docs"
echo
echo "Пока идёт показ, компьютер не должен засыпать: см. README.md, раздел «Не засыпать»."
