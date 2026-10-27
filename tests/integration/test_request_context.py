from httpx import AsyncClient
from starlette.types import Message, Receive, Scope, Send

from chatbot_api.core.logging import RequestContextMiddleware, resolve_request_id
from chatbot_api.core.rate_limit import RateLimiter, RateLimitMiddleware

VALID_REQUEST_ID = "client-request-0001"


async def test_echoes_valid_request_id(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": VALID_REQUEST_ID})

    assert response.headers["x-request-id"] == VALID_REQUEST_ID


async def test_replaces_invalid_request_id(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "bad id\r\ninjected"})

    assert response.headers["x-request-id"] != "bad id\r\ninjected"
    assert len(response.headers["x-request-id"]) == 32


def test_generates_request_id_when_missing() -> None:
    assert len(resolve_request_id([])) == 32


async def test_passes_through_non_http_scopes() -> None:
    received: list[str] = []

    async def inner_app(scope: Scope, _: Receive, __: Send) -> None:
        received.append(scope["type"])

    async def receive() -> Message:
        return {}

    async def send(_: Message) -> None:
        return None

    await RequestContextMiddleware(inner_app)({"type": "lifespan"}, receive, send)

    assert received == ["lifespan"]


async def test_rate_limit_passes_through_non_http_scopes() -> None:
    received: list[str] = []

    async def inner_app(scope: Scope, _: Receive, __: Send) -> None:
        received.append(scope["type"])

    async def receive() -> Message:
        return {}

    async def send(_: Message) -> None:
        return None

    middleware = RateLimitMiddleware(inner_app, RateLimiter("1/minute"))
    await middleware({"type": "lifespan"}, receive, send)

    assert received == ["lifespan"]
