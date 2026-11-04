#!/usr/bin/env bash
# Проверка, что на Mac есть всё для работы над GoPoint.
# Запуск: bash scripts/check-mac.sh
set -u

ok=1
line() { printf "  %-16s %s\n" "$1" "$2"; }

echo "Проверка компьютера для GoPoint"
echo

arch="$(uname -m)"
if [ "$arch" = "arm64" ]; then line "Процессор" "Apple Silicon"; else line "Процессор" "Intel ($arch)"; fi

if command -v git >/dev/null 2>&1; then line "Git" "$(git --version | awk '{print $3}')"
else line "Git" "НЕТ: установите Xcode Command Line Tools (xcode-select --install)"; ok=0; fi

if command -v node >/dev/null 2>&1; then
  major="$(node -p 'process.versions.node.split(".")[0]')"
  if [ "$major" -ge 22 ]; then line "Node.js" "$(node --version)"
  else line "Node.js" "$(node --version): слишком старая, нужна 22 или новее (nodejs.org, LTS)"; ok=0; fi
else line "Node.js" "НЕТ: скачайте LTS с nodejs.org"; ok=0; fi

if command -v uv >/dev/null 2>&1; then
  line "uv" "$(uv --version | awk '{print $2}')"
  if uv python find 3.12 >/dev/null 2>&1; then line "Python 3.12" "$(uv python find 3.12)"
  else line "Python 3.12" "НЕТ: выполните uv python install 3.12"; ok=0; fi
else line "uv" "НЕТ: установите по инструкции docs.astral.sh/uv"; ok=0; fi

if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    mem_gb="$(docker info --format '{{.MemTotal}}' | awk '{printf "%.1f", $1/1073741824}')"
    line "Docker" "$(docker --version | awk '{print $3}' | tr -d ,) запущен, памяти для контейнеров ${mem_gb} ГБ"
    if ! docker compose version >/dev/null 2>&1; then line "Docker Compose" "НЕТ"; ok=0; fi
  else line "Docker" "установлен, но не запущен: откройте Docker Desktop"; ok=0; fi
else line "Docker" "НЕТ: установите Docker Desktop с docker.com"; ok=0; fi

echo
if [ "$ok" -eq 1 ]; then echo "всё готово"; exit 0; else echo "не всё готово: см. строки выше"; exit 1; fi
