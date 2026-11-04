#!/usr/bin/env bash
# Временный HTTPS-адрес для проверки GoPoint на телефоне (работает и «Моё местоположение»).
#   bash scripts/run-tunnel.sh   запустить и напечатать адрес
#   bash scripts/stop-tunnel.sh  выключить
#
# Туннель идёт через бесплатный сервис localhost.run по SSH, регистрация не нужна.
# Пока он работает, сайт открывается из интернета по случайному адресу *.lhr.life.
# Выключайте его сразу после проверки: письменного разрешения ЦУГАЭТ пока нет.
set -euo pipefail
cd "$(dirname "$0")/.."

state_dir="${TMPDIR:-/tmp}/gopoint-tunnel"
mkdir -p "$state_dir"
pid_file="$state_dir/pid"
log_file="$state_dir/log"

port="$(grep -E '^GOPOINT_HTTP_PORT=' .env 2>/dev/null | cut -d= -f2 || true)"
port="${port:-8080}"
if ! curl -fsS "http://localhost:${port}/health" >/dev/null 2>&1; then
  echo "Сначала запустите демо: bash scripts/run-demo.sh"
  exit 1
fi

if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
  echo "Туннель уже работает. Адрес:"
  grep -oE 'https://[a-z0-9.-]+\.lhr\.life' "$log_file" | tail -1
  exit 0
fi

echo "Запускаю временный туннель..."
# Ключи SSH и файл known_hosts на Mac не используются и не меняются.
nohup ssh -T \
  -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -o LogLevel=ERROR \
  -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
  -R "80:localhost:${port}" nokey@localhost.run </dev/null >"$log_file" 2>&1 &
echo $! >"$pid_file"

url=""
for _ in $(seq 1 30); do
  url="$(grep -oE 'https://[a-z0-9.-]+\.lhr\.life' "$log_file" 2>/dev/null | tail -1 || true)"
  [ -n "$url" ] && break
  if ! kill -0 "$(cat "$pid_file")" 2>/dev/null; then break; fi
  sleep 1
done
if [ -z "$url" ]; then
  echo "Туннель не запустился. Что ответил сервис:"
  tail -5 "$log_file"
  bash scripts/stop-tunnel.sh >/dev/null
  exit 1
fi

echo
echo "Адрес для телефона (работает через мобильный интернет и любой Wi-Fi):"
echo "  $url"
echo
echo "Адрес случайный и меняется при каждом запуске. Если сайт перестал открываться,"
echo "запустите эту команду снова. Пока туннель работает, сайт доступен из интернета."
echo "Выключить: bash scripts/stop-tunnel.sh"
