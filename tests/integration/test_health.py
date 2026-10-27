from http import HTTPStatus

from fastapi import FastAPI
from httpx import AsyncClient


async def test_health_is_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ok"}


async def test_ready_without_checks(client: AsyncClient) -> None:
    response = await client.get("/ready")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ready"}


async def test_ready_fails_when_a_check_fails(app: FastAPI, client: AsyncClient) -> None:
    async def passing() -> bool:
        return True

    async def failing() -> bool:
        return False

    app.state.readiness_checks.extend([passing, failing])

    response = await client.get("/ready")

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.json() == {"status": "not_ready"}
