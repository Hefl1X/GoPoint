#!/usr/bin/env bash
# Остановка демо GoPoint: bash scripts/stop-demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/stop-tunnel.sh >/dev/null 2>&1 || true
docker compose down
echo "GoPoint остановлен."
