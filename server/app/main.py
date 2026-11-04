"""Точка входа сервера GoPoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import v1
from app.api.errors import install_error_handlers
from app.api.schemas import Health
from app.config import APP_NAME, APP_VERSION, get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{APP_NAME} API",
        version=APP_VERSION,
        description="Транспорт Новосибирска на линии сейчас и маршруты по низкопольным машинам.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    install_error_handlers(app)
    app.include_router(v1.router)

    @app.get("/health", include_in_schema=False)
    async def root_health() -> Health:
        return Health()

    return app


app = create_app()
