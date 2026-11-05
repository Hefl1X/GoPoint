"""Единый формат ошибок: {code, message, details}. Сообщения по-русски."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.models import ApiError

log = logging.getLogger(__name__)


class AppError(Exception):
    """Ошибка, которую сервер сознательно отдаёт клиенту."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error = ApiError(code=code, message=message, details=details)


def not_implemented() -> AppError:
    return AppError(501, "NOT_IMPLEMENTED", "Эта функция ещё в разработке.")


_HTTP_MESSAGES: dict[int, tuple[str, str]] = {
    404: ("NOT_FOUND", "Ничего не нашлось по этому адресу."),
    405: ("METHOD_NOT_ALLOWED", "Такой запрос здесь не поддерживается."),
    429: ("TOO_MANY_REQUESTS", "Слишком много запросов. Подождите немного."),
}


def api_error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """Ответ с ошибкой в едином формате (для middleware, где исключения не ловятся)."""
    return _response(status_code, ApiError(code=code, message=message, details=None))


def _response(status_code: int, error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json", by_alias=True, exclude_none=True),
    )


async def _app_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return _response(exc.status_code, exc.error)


async def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code, message = _HTTP_MESSAGES.get(
        exc.status_code, ("HTTP_ERROR", "Запрос не удалось выполнить.")
    )
    return _response(exc.status_code, ApiError(code=code, message=message))


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # В подробностях только путь к полю и тип ошибки, без присланных значений:
    # там могут быть координаты пользователя.
    fields = [
        {"field": ".".join(str(p) for p in err.get("loc", ())), "type": err.get("type")}
        for err in exc.errors()
    ]
    error = ApiError(
        code="VALIDATION_ERROR",
        message="Проверьте введённые данные.",
        details={"fields": fields},
    )
    return _response(422, error)


async def _unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    log.exception("Необработанная ошибка: %s", type(exc).__name__)
    error = ApiError(code="INTERNAL", message="Что-то пошло не так на сервере. Попробуйте позже.")
    return _response(500, error)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unexpected_error)


ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    422: {"model": ApiError, "description": "Неверные данные запроса"},
    500: {"model": ApiError, "description": "Ошибка сервера"},
    501: {"model": ApiError, "description": "Ещё не сделано"},
}
