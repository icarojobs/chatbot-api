from enum import StrEnum
from http import HTTPStatus
from typing import cast

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)


class ErrorType(StrEnum):
    INVALID_REQUEST = "invalid_request_error"
    AUTHENTICATION = "authentication_error"
    PERMISSION = "permission_error"
    NOT_FOUND = "not_found_error"
    RATE_LIMIT = "rate_limit_error"
    SERVER = "server_error"


ERROR_TYPE_BY_STATUS = {
    HTTPStatus.UNAUTHORIZED: ErrorType.AUTHENTICATION,
    HTTPStatus.FORBIDDEN: ErrorType.PERMISSION,
    HTTPStatus.NOT_FOUND: ErrorType.NOT_FOUND,
    HTTPStatus.TOO_MANY_REQUESTS: ErrorType.RATE_LIMIT,
}

GENERIC_SERVER_ERROR_MESSAGE = "Erro interno. Tente novamente mais tarde."
RATE_LIMIT_MESSAGE = "Limite de requisições excedido. Aguarde e tente novamente."
VALIDATION_MESSAGE = "Requisição inválida."


class ApiError(Exception):
    def __init__(
        self,
        status_code: HTTPStatus,
        message: str,
        error_type: ErrorType = ErrorType.INVALID_REQUEST,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.error_type = error_type
        self.code = code
        self.headers = headers


def error_response(
    status_code: int,
    message: str,
    error_type: ErrorType,
    code: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {"error": {"message": message, "type": error_type, "param": None, "code": code}}
    return JSONResponse(status_code=status_code, content=body, headers=headers)


async def handle_api_error(_: Request, exc: Exception) -> JSONResponse:
    api_error = cast(ApiError, exc)
    return error_response(
        api_error.status_code,
        api_error.message,
        api_error.error_type,
        api_error.code,
        api_error.headers,
    )


async def handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    http_error = cast(StarletteHTTPException, exc)
    error_type = ERROR_TYPE_BY_STATUS.get(
        HTTPStatus(http_error.status_code), ErrorType.INVALID_REQUEST
    )
    headers = dict(http_error.headers) if http_error.headers else None
    return error_response(
        http_error.status_code, str(http_error.detail), error_type, headers=headers
    )


async def handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    validation_error = cast(RequestValidationError, exc)
    first_error = validation_error.errors()[0]
    location = ".".join(str(part) for part in first_error["loc"])
    message = f"{VALIDATION_MESSAGE} {location}: {first_error['msg']}"
    return error_response(HTTPStatus.BAD_REQUEST, message, ErrorType.INVALID_REQUEST)


async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error", error_class=type(exc).__name__)
    return error_response(
        HTTPStatus.INTERNAL_SERVER_ERROR, GENERIC_SERVER_ERROR_MESSAGE, ErrorType.SERVER
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, handle_api_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
