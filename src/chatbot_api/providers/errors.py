from http import HTTPStatus

import openai
import structlog

from chatbot_api.core.errors import ApiError, ErrorType

logger = structlog.get_logger(__name__)

PROVIDER_TIMEOUT = (
    HTTPStatus.GATEWAY_TIMEOUT,
    "O provedor de modelos demorou demais para responder.",
    "provider_timeout",
)
PROVIDER_UNAVAILABLE = (
    HTTPStatus.BAD_GATEWAY,
    "O provedor de modelos está indisponível no momento.",
    "provider_unavailable",
)
PROVIDER_RATE_LIMITED = (
    HTTPStatus.SERVICE_UNAVAILABLE,
    "O provedor de modelos atingiu o limite de requisições. Tente novamente em instantes.",
    "provider_rate_limited",
)
PROVIDER_FAILED = (
    HTTPStatus.BAD_GATEWAY,
    "O provedor de modelos retornou um erro.",
    "provider_error",
)

ERROR_BY_PROVIDER_EXCEPTION: tuple[
    tuple[type[openai.APIError], tuple[HTTPStatus, str, str]], ...
] = (
    (openai.APITimeoutError, PROVIDER_TIMEOUT),
    (openai.APIConnectionError, PROVIDER_UNAVAILABLE),
    (openai.RateLimitError, PROVIDER_RATE_LIMITED),
)


def translate_provider_error(exc: openai.APIError) -> ApiError:
    status, message, code = next(
        (error for kind, error in ERROR_BY_PROVIDER_EXCEPTION if isinstance(exc, kind)),
        PROVIDER_FAILED,
    )
    logger.warning(
        "provider_error",
        error_class=type(exc).__name__,
        provider_status=getattr(exc, "status_code", None),
    )
    return ApiError(status, message, ErrorType.SERVER, code)
