from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from chatbot_api.core.config import Settings
from chatbot_api.db import migrate
from chatbot_api.db.session import SessionFactory, create_session_factory
from chatbot_api.main import create_app

ACCESS_TOKEN = "a" * 40
ADMIN_TOKEN = "b" * 40
TEST_BASE_URL = "http://testserver"
DATA_TABLES = "chunk_embeddings, chunks, documents"

SettingsFactory = Callable[..., Settings]


class TestEnvironment(BaseSettings):
    """Only the isolated test database is read from the environment / .env."""

    __test__ = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    test_database_url: str


TEST_DATABASE_URL = TestEnvironment().test_database_url


def _execute(statement: str) -> None:
    engine = create_engine(TEST_DATABASE_URL, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(text(statement))
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    _execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    migrate.upgrade(TEST_DATABASE_URL)


@pytest.fixture
async def session_factory() -> AsyncIterator[SessionFactory]:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    yield create_session_factory(engine)
    await engine.dispose()
    _execute(f"TRUNCATE {DATA_TABLES} CASCADE")


@pytest.fixture
def settings_factory() -> SettingsFactory:
    def build(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "database_url": TEST_DATABASE_URL,
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
async def app_factory() -> AsyncIterator[Callable[[Settings], FastAPI]]:
    created: list[FastAPI] = []

    def build(app_settings: Settings) -> FastAPI:
        created.append(create_app(app_settings))
        return created[-1]

    yield build
    for application in created:
        await application.state.engine.dispose()


@pytest.fixture
def app(settings: Settings, app_factory: Callable[[Settings], FastAPI]) -> FastAPI:
    return app_factory(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url=TEST_BASE_URL) as http_client:
        yield http_client


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
