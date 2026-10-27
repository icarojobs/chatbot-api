import hmac
from collections.abc import Callable
from http import HTTPStatus
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr

from chatbot_api.core.config import Settings
from chatbot_api.core.errors import ApiError, ErrorType

AUTHENTICATION_FAILED_MESSAGE = "Token de acesso ausente ou inválido."
WWW_AUTHENTICATE_HEADERS = {"WWW-Authenticate": "Bearer"}

bearer_scheme = HTTPBearer(auto_error=False)

BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]
TokenSelector = Callable[[Settings], SecretStr]


def _is_valid_token(credentials: HTTPAuthorizationCredentials | None, expected: SecretStr) -> bool:
    if credentials is None:
        return False
    return hmac.compare_digest(
        credentials.credentials.encode(), expected.get_secret_value().encode()
    )


def _token_guard(select_token: TokenSelector) -> Callable[[Request, BearerCredentials], None]:
    def guard(request: Request, credentials: BearerCredentials) -> None:
        settings: Settings = request.app.state.settings
        if _is_valid_token(credentials, select_token(settings)):
            return
        raise ApiError(
            HTTPStatus.UNAUTHORIZED,
            AUTHENTICATION_FAILED_MESSAGE,
            ErrorType.AUTHENTICATION,
            "invalid_api_key",
            WWW_AUTHENTICATE_HEADERS,
        )

    return guard


require_access_token = _token_guard(lambda settings: settings.api_access_token)
require_admin_token = _token_guard(lambda settings: settings.api_admin_token)
