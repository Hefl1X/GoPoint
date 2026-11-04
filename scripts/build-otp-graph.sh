#!/usr/bin/env bash
# Сборка графа улиц для пеших участков (OpenTripPlanner) одной командой:
#   bash scripts/build-otp-graph.sh          (скачает данные, если их ещё нет)
#   bash scripts/build-otp-graph.sh --fresh  (скачает свежие улицы)
#   bash scripts/build-otp-graph.sh --with-dem  (добавит рельеф Copernicus; по умолчанию выключен:
#        это модель поверхности с крышами и деревьями, уклоны тротуаров по ней неверны, см. DECISIONS.md)
# Что делает:
#   1. скачивает улицы OpenStreetMap по Сибирскому округу (Geofabrik, ~590 МБ) и вырезает
#      прямоугольник города с запасом (osmium);
#   2. только с --with-dem: скачивает рельеф Copernicus DEM GLO-30 (4 файла по ~30 МБ, AWS Open Data);
#   3. собирает граф OpenTripPlanner в data/otp/graph.obj и перезапускает сервис otp.
# Занимает 5–15 минут. Повторять раз в несколько месяцев, чтобы обновить улицы.
set -euo pipefail
cd "$(dirname "$0")/.."

OSM_URL="https://download.geofabrik.de/russia/siberian-fed-district-latest.osm.pbf"
DEM_BASE="https://copernicus-dem-30m.s3.amazonaws.com"
OSM_RAW="data/osm/siberian-fed-district.osm.pbf"
OUT="data/otp"

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
# Запас 0,02° (~2 км): улицы у самой границы города тоже связаны с сетью.
crop="$(python3 -c "print(f'{$west-0.02},{$south-0.02},{$east+0.02},{$north+0.02}')")"

fresh=0; with_dem=0
for arg in "$@"; do
  case "$arg" in
    --fresh) fresh=1 ;;
    --with-dem) with_dem=1 ;;
    *) echo "Неизвестный параметр: $arg"; exit 1 ;;
  esac
done

mkdir -p data/osm "$OUT"
if [ "$fresh" = 1 ] || [ ! -s "$OSM_RAW" ]; then
  echo "Скачиваю улицы OpenStreetMap по Сибири (около 590 МБ)..."
  curl -fL --progress-bar -o "$OSM_RAW.part" "$OSM_URL"
  mv "$OSM_RAW.part" "$OSM_RAW"
fi

echo "Вырезаю Новосибирск ($crop)..."
docker build -q -t gopoint-osm-tools:local -f otp/tools.Dockerfile otp >/dev/null
docker run --rm -v "$PWD/data:/data" gopoint-osm-tools:local \
  extract --bbox "$crop" --strategy complete_ways --overwrite \
  -o /data/otp/novosibirsk.osm.pbf /data/osm/siberian-fed-district.osm.pbf

cp otp/build-config.json otp/router-config.json "$OUT/"
rm -f "$OUT"/dem_*.tif
if [ "$with_dem" = 1 ]; then
  dem_list=""
  for tile in N54_00_E082_00 N54_00_E083_00 N55_00_E082_00 N55_00_E083_00; do
    short="$(echo "$tile" | sed -E 's/_00//g')"
    dest="data/osm/dem_${short}.tif"
    if [ ! -s "$dest" ]; then
      echo "Скачиваю рельеф $tile..."
      curl -fsSL -o "$dest.part" "$DEM_BASE/Copernicus_DSM_COG_10_${tile}_DEM/Copernicus_DSM_COG_10_${tile}_DEM.tif"
      mv "$dest.part" "$dest"
    fi
    cp "$dest" "$OUT/"
    dem_list="$dem_list{\"source\":\"dem_${short}.tif\"},"
  done
  python3 - "$OUT/build-config.json" "[${dem_list%,}]" <<'PY'
import json, sys
path, dem = sys.argv[1], json.loads(sys.argv[2])
config = json.load(open(path))
config["dem"] = dem
json.dump(config, open(path, "w"), indent=2)
PY
fi

echo "Собираю граф улиц (несколько минут)..."
docker compose stop otp >/dev/null 2>&1 || true
docker compose run --rm --no-deps -e JAVA_TOOL_OPTIONS="$(env_value GOPOINT_OTP_BUILD_JAVA_OPTS -Xmx3g)" \
  otp --build --save

docker compose up -d otp
echo "Готово: граф собран, пешие участки считаются по улицам Новосибирска."
echo "Файл $OSM_RAW нужен только для обновления, его можно удалить."
