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

port="$(grep -E '^GOPOINT_HTTP_PORT=' .env | cut -d= -f2 || true)"
port="${port:-8080}"

echo "Собираю и запускаю GoPoint (первый раз это может занять несколько минут)..."
docker compose up -d --build

echo -n "Жду, пока сервис ответит"
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:${port}/health" >/dev/null 2>&1; then
    echo " готово."
    break
  fi
  echo -n "."
  sleep 2
done
if ! curl -fsS "http://localhost:${port}/health" >/dev/null 2>&1; then
  echo
  echo "Сервис не ответил за 2 минуты. Что показывают контейнеры:"
  docker compose ps
  echo "Подробности: docker compose logs --tail 50"
  exit 1
fi

# База поиска адресов собирается отдельно (один раз, около 5 минут).
if ! docker compose exec -T photon test -d /data/photon_data >/dev/null 2>&1; then
  echo
  echo "Внимание: база поиска адресов ещё не собрана, подсказки адресов работать не будут."
  echo "Соберите её один раз: bash scripts/build-photon-db.sh"
fi

if [ ! -f data/otp/graph.obj ]; then
  echo
  echo "Внимание: граф улиц не собран, пешие участки считаться не будут."
  echo "Соберите его один раз: bash scripts/build-otp-graph.sh"
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
