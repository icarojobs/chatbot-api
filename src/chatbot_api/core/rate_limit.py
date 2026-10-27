import math
import time
from http import HTTPStatus

from limits import RateLimitItem, parse
from limits.aio.storage import MemoryStorage
from limits.aio.strategies import MovingWindowRateLimiter
from starlette.types import ASGIApp, Receive, Scope, Send

from chatbot_api.core.errors import RATE_LIMIT_MESSAGE, ErrorType, error_response

UNKNOWN_CLIENT = "unknown"
RATE_LIMIT_CODE = "rate_limit_exceeded"
FORWARDED_FOR_HEADER = b"x-forwarded-for"
FORWARDED_FOR_SEPARATOR = ","


class RateLimiter:
    def __init__(self, default_limit: str) -> None:
        self._limit: RateLimitItem = parse(default_limit)
        self._strategy = MovingWindowRateLimiter(MemoryStorage())

    async def hit(self, key: str) -> bool:
        return await self._strategy.hit(self._limit, key)

    async def seconds_until_reset(self, key: str) -> int:
        stats = await self._strategy.get_window_stats(self._limit, key)
        return max(1, math.ceil(stats.reset_time - time.time()))


def _forwarded_client(scope: Scope, trusted_proxy_hops: int) -> str | None:
    raw_header = dict(scope.get("headers", [])).get(FORWARDED_FOR_HEADER)
    if raw_header is None:
        return None
    hops = [hop.strip() for hop in raw_header.decode("latin-1").split(FORWARDED_FOR_SEPARATOR)]
    if len(hops) < trusted_proxy_hops:
        return None
    return hops[-trusted_proxy_hops] or None


def client_key(scope: Scope, trusted_proxy_hops: int = 0) -> str:
    """Only the hops appended by trusted proxies are used: leftmost values are client-controlled."""
    if trusted_proxy_hops > 0:
        forwarded = _forwarded_client(scope, trusted_proxy_hops)
        if forwarded:
            return forwarded
    client = scope.get("client")
    return client[0] if client else UNKNOWN_CLIENT


class RateLimitMiddleware:
    """Pure ASGI middleware: rejects before the app runs and never touches streaming bodies."""

    def __init__(self, app: ASGIApp, limiter: RateLimiter, trusted_proxy_hops: int = 0) -> None:
        self.app = app
        self.limiter = limiter
        self.trusted_proxy_hops = trusted_proxy_hops

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        key = client_key(scope, self.trusted_proxy_hops)
        if await self.limiter.hit(key):
            await self.app(scope, receive, send)
            return

        retry_after = await self.limiter.seconds_until_reset(key)
        response = error_response(
            HTTPStatus.TOO_MANY_REQUESTS,
            RATE_LIMIT_MESSAGE,
            ErrorType.RATE_LIMIT,
            RATE_LIMIT_CODE,
            {"Retry-After": str(retry_after)},
        )
        await response(scope, receive, send)
