#!/usr/bin/env bash
# Подготовка расписания из уже сохранённого архива, без запросов к ЦУГАЭТ.
set -euo pipefail
cd "$(dirname "$0")/.."
root="$PWD"
service_end="${1:?Укажите последний день демо: bash scripts/prepare-demo.sh 2026-12-20}"
service_start="$(TZ=Asia/Novosibirsk date +%F)"
store="${GOPOINT_RT_DIR:-$root/data/otp/demo}"
mkdir -p "$store"
store="$(cd "$store" && pwd)"

echo "Готовлю демо по сохранённому расписанию: $service_start — $service_end."
echo "Время поездок ориентировочное; сезонные изменения и праздники не проверены."
cd server
uv run --locked python -m tools.audit_city_schedule \
  --metadata "$root/data/otp/tsugaet-metadata-2026-11-24" \
  --archive "$root/data/otp/tsugaet-full-2026-11-24" \
  --stop-reviews "$root/data/tsugaet/stop-reviews-2026-11-24.json" \
  --output "$store/schedule-$service_start-$service_end" \
  --service-start "$service_start" --service-end "$service_end"
uv run --locked python -m tools.build_otp_artifacts prepare \
  --store "$store" --osm "$root/data/otp/novosibirsk.osm.pbf" \
  --schedule "$store/schedule-$service_start-$service_end" | tee "$store/build.log"
release="$(tail -n 1 "$store/build.log")"
version="$(basename "$release")"
uv run --locked python -m tools.demo_release --store "$store" --version "$version"
printf '%s\n' "$version" > "$store/current.tmp"
mv "$store/current.tmp" "$store/current"
echo "Комплект готов. Запуск: bash scripts/run-demo.sh"
