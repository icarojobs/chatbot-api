import logging
import re
import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")
MILLISECONDS_PER_SECOND = 1000
NOISY_LOGGERS = ("httpx", "httpx2", "httpcore", "openai")

logger = structlog.get_logger(__name__)


def configure_logging(log_level: str) -> None:
    logging.basicConfig(format="%(message)s", level=log_level)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[log_level]
        ),
        cache_logger_on_first_use=True,
    )


def resolve_request_id(headers: list[tuple[bytes, bytes]]) -> str:
    received = dict(headers).get(REQUEST_ID_HEADER.encode(), b"").decode("latin-1")
    if REQUEST_ID_PATTERN.fullmatch(received):
        return received
    return uuid.uuid4().hex


class RequestContextMiddleware:
    """Pure ASGI middleware so streaming responses are not buffered."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = resolve_request_id(scope["headers"])
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started_at = time.perf_counter()
        status_code = 0

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (REQUEST_ID_HEADER.encode(), request_id.encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            logger.info(
                "request_finished",
                method=scope["method"],
                path=scope["path"],
                status_code=status_code,
                duration_ms=round((time.perf_counter() - started_at) * MILLISECONDS_PER_SECOND, 2),
            )
