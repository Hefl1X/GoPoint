#!/usr/bin/env bash
# Остановка демо GoPoint: bash scripts/stop-demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose down
echo "GoPoint остановлен."
