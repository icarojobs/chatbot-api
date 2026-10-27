from http import HTTPStatus

import pytest
from fastapi import Depends, FastAPI
from httpx import AsyncClient

from chatbot_api.core.security import require_access_token, require_admin_token
from tests.conftest import ACCESS_TOKEN, ADMIN_TOKEN, auth_header


@pytest.fixture(autouse=True)
def protected_routes(app: FastAPI) -> None:
    @app.get("/protected", dependencies=[Depends(require_access_token)])
    async def protected() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/admin", dependencies=[Depends(require_admin_token)])
    async def admin() -> dict[str, bool]:
        return {"ok": True}


async def test_rejects_missing_token(client: AsyncClient) -> None:
    response = await client.get("/protected")

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"] == {
        "message": "Token de acesso ausente ou inválido.",
        "type": "authentication_error",
        "param": None,
        "code": "invalid_api_key",
    }


async def test_rejects_wrong_token(client: AsyncClient) -> None:
    response = await client.get("/protected", headers=auth_header("x" * 40))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


async def test_accepts_access_token(client: AsyncClient) -> None:
    response = await client.get("/protected", headers=auth_header(ACCESS_TOKEN))

    assert response.status_code == HTTPStatus.OK


async def test_admin_route_rejects_access_token(client: AsyncClient) -> None:
    response = await client.get("/admin", headers=auth_header(ACCESS_TOKEN))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


async def test_admin_route_accepts_admin_token(client: AsyncClient) -> None:
    response = await client.get("/admin", headers=auth_header(ADMIN_TOKEN))

    assert response.status_code == HTTPStatus.OK
