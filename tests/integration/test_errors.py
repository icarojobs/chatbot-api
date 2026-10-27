from http import HTTPStatus

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from chatbot_api.core.errors import ApiError, ErrorType
from chatbot_api.main import create_app
from tests.conftest import TEST_BASE_URL, SettingsFactory

SECRET_DETAIL = "db password=hunter2"


@pytest.fixture(autouse=True)
def failing_routes(app: FastAPI) -> None:
    @app.get("/api-error")
    async def api_error() -> None:
        raise ApiError(HTTPStatus.CONFLICT, "Conflito.", ErrorType.INVALID_REQUEST, "conflict")

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError(SECRET_DETAIL)

    @app.get("/typed")
    async def typed(limit: int) -> dict[str, int]:
        return {"limit": limit}


async def test_api_error_uses_openai_format(client: AsyncClient) -> None:
    response = await client.get("/api-error")

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json() == {
        "error": {
            "message": "Conflito.",
            "type": "invalid_request_error",
            "param": None,
            "code": "conflict",
        }
    }


async def test_unknown_route_returns_not_found_error(client: AsyncClient) -> None:
    response = await client.get("/missing")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["error"]["type"] == "not_found_error"


async def test_validation_error_returns_bad_request(client: AsyncClient) -> None:
    response = await client.get("/typed", params={"limit": "abc"})

    assert response.status_code == HTTPStatus.BAD_REQUEST
    error = response.json()["error"]
    assert error["type"] == "invalid_request_error"
    assert error["message"].startswith("Requisição inválida. query.limit:")


async def test_unexpected_error_hides_details(client: AsyncClient) -> None:
    response = await client.get("/boom")

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.json()["error"]["type"] == "server_error"
    assert SECRET_DETAIL not in response.text


async def test_rate_limit_applies_to_every_route(settings_factory: SettingsFactory) -> None:
    app = create_app(settings_factory(rate_limit_default="2/minute"))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url=TEST_BASE_URL) as client:
        statuses = [(await client.get("/health")).status_code for _ in range(2)]
        limited = await client.get("/ready")

    assert statuses == [HTTPStatus.OK, HTTPStatus.OK]
    assert limited.status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert limited.json()["error"]["code"] == "rate_limit_exceeded"
    assert int(limited.headers["retry-after"]) >= 1
