#!/usr/bin/env bash
# Сборка базы поиска адресов только по Новосибирску одной командой:
#   bash scripts/build-photon-db.sh
# Что делает:
#   1. скачивает выгрузку Photon по России (около 1,5 ГБ, GraphHopper), если её ещё нет
#      или если запущено с --fresh;
#   2. оставляет только прямоугольник города (границы GOPOINT_CITY_* из .env);
#   3. собирает базу в томе Docker photon_data и перезапускает поиск.
# Повторять раз в несколько месяцев, чтобы обновить адреса. Занимает 10–20 минут.
set -euo pipefail
cd "$(dirname "$0")/.."

DUMP_URL="https://download1.graphhopper.com/public/europe/russia/photon-dump-russia-1.0-latest.jsonl.zst"
DUMP="data/photon/photon-dump-russia.jsonl.zst"

if ! docker info >/dev/null 2>&1; then
  echo "Docker не запущен. Откройте Docker Desktop и запустите команду снова."
  exit 1
fi

env_value() {
  local v=""
  [ -f .env ] && v="$(grep -E "^$1=" .env | cut -d= -f2 || true)"
  echo "${v:-$2}"
}
south="$(env_value GOPOINT_CITY_SOUTH 54.80)"
west="$(env_value GOPOINT_CITY_WEST 82.70)"
north="$(env_value GOPOINT_CITY_NORTH 55.20)"
east="$(env_value GOPOINT_CITY_EAST 83.20)"

mkdir -p data/photon
if [ "${1:-}" = "--fresh" ] || [ ! -s "$DUMP" ]; then
  echo "Скачиваю выгрузку адресов по России (около 1,5 ГБ)..."
  curl -fL --progress-bar -o "$DUMP.part" "$DUMP_URL"
  mv "$DUMP.part" "$DUMP"
fi

echo "Собираю базу поиска по Новосибирску ($south,$west — $north,$east)..."
docker compose build photon
docker compose stop photon >/dev/null 2>&1 || true
docker compose run --rm --no-deps -v "$PWD/data/photon:/input:ro" photon \
  /opt/import.sh /input/photon-dump-russia.jsonl.zst "$south,$west,$north,$east"

docker compose up -d photon
echo "Готово. Поиск адресов работает на своей базе."
echo "Файл выгрузки $DUMP больше не нужен для работы: его можно удалить (он понадобится только для обновления)."
