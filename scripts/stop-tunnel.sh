#!/usr/bin/env bash
# Выключить временный HTTPS-туннель: bash scripts/stop-tunnel.sh
set -euo pipefail
pid_file="${TMPDIR:-/tmp}/gopoint-tunnel/pid"
if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
  kill "$(cat "$pid_file")"
fi
rm -f "$pid_file"
echo "Туннель выключен: сайт больше не доступен из интернета."
