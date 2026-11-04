"""Выгрузка контракта OpenAPI в файл, из него генерируются типы сайта.

Запуск: uv run python -m app.openapi_export ../web/src/adapters/api/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.main import create_app


def render() -> str:
    return json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Укажите путь к файлу: python -m app.openapi_export <файл>")
    Path(sys.argv[1]).write_text(render(), encoding="utf-8")


if __name__ == "__main__":
    main()
