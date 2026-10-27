from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from chatbot_api.core.config import Settings
from chatbot_api.main import create_app

ACCESS_TOKEN = "a" * 40
ADMIN_TOKEN = "b" * 40
TEST_BASE_URL = "http://testserver"

SettingsFactory = Callable[..., Settings]


@pytest.fixture
def settings_factory() -> SettingsFactory:
    def build(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "api_access_token": ACCESS_TOKEN,
            "api_admin_token": ADMIN_TOKEN,
            "rate_limit_default": "1000/minute",
            **overrides,
        }
        return Settings(_env_file=None, **values)

    return build


@pytest.fixture
def settings(settings_factory: SettingsFactory) -> Settings:
    return settings_factory()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url=TEST_BASE_URL) as http_client:
        yield http_client


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
