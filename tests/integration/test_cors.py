from collections.abc import Callable

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from chatbot_api.core.config import Settings
from tests.conftest import ACCESS_TOKEN, TEST_BASE_URL, SettingsFactory, auth_header

BROWSER_ORIGIN = "https://chatbot.example.com"
FILE_ORIGIN = "null"
CHAT_PATH = "/v1/chat/completions"


def preflight_headers(origin: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization, content-type",
    }


async def test_preflight_allows_any_origin_by_default(client: AsyncClient) -> None:
    response = await client.options(CHAT_PATH, headers=preflight_headers(BROWSER_ORIGIN))

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "authorization" in response.headers["access-control-allow-headers"]
    assert "access-control-allow-credentials" not in response.headers


async def test_preflight_allows_html_opened_from_file(client: AsyncClient) -> None:
    response = await client.options(CHAT_PATH, headers=preflight_headers(FILE_ORIGIN))

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


async def test_simple_response_exposes_cors_headers(client: AsyncClient) -> None:
    response = await client.get(
        "/v1/models", headers={"Origin": BROWSER_ORIGIN, **auth_header(ACCESS_TOKEN)}
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "x-request-id" in response.headers["access-control-expose-headers"]


async def test_error_responses_keep_cors_headers(client: AsyncClient) -> None:
    response = await client.get("/v1/models", headers={"Origin": BROWSER_ORIGIN})

    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "*"


async def test_rate_limited_responses_keep_cors_headers(
    settings_factory: SettingsFactory, app_factory: Callable[[Settings], FastAPI]
) -> None:
    app = app_factory(settings_factory(rate_limit_default="1/minute"))
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url=TEST_BASE_URL) as http_client:
        await http_client.get("/health", headers={"Origin": BROWSER_ORIGIN})
        response = await http_client.get("/health", headers={"Origin": BROWSER_ORIGIN})

    assert response.status_code == 429
    assert response.headers["access-control-allow-origin"] == "*"
    assert "retry-after" in response.headers["access-control-expose-headers"]


async def test_restricted_origins_reject_unknown_origin(
    settings_factory: SettingsFactory, app_factory: Callable[[Settings], FastAPI]
) -> None:
    app = app_factory(settings_factory(cors_allowed_origins=BROWSER_ORIGIN))
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url=TEST_BASE_URL) as http_client:
        allowed = await http_client.options(CHAT_PATH, headers=preflight_headers(BROWSER_ORIGIN))
        denied = await http_client.options(
            CHAT_PATH, headers=preflight_headers("https://evil.example.com")
        )

    assert allowed.headers["access-control-allow-origin"] == BROWSER_ORIGIN
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
