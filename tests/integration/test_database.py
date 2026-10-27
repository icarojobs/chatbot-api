from http import HTTPStatus

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

from chatbot_api.db import migrate
from chatbot_api.main import create_app
from tests.conftest import TEST_BASE_URL, TEST_DATABASE_URL, SettingsFactory


def test_migrations_are_idempotent_and_create_schema(
    monkeypatch: pytest.MonkeyPatch, settings_factory: SettingsFactory
) -> None:
    monkeypatch.setattr(migrate, "get_settings", settings_factory)

    migrate.main()

    engine = create_engine(TEST_DATABASE_URL, poolclass=NullPool)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert {"documents", "chunks", "chunk_embeddings", "alembic_version"} <= tables


async def test_ready_when_database_is_reachable(client: AsyncClient) -> None:
    response = await client.get("/ready")

    assert response.status_code == HTTPStatus.OK


async def test_not_ready_when_database_is_unreachable(settings_factory: SettingsFactory) -> None:
    app = create_app(
        settings_factory(database_url="postgresql+psycopg://user:pass@127.0.0.1:1/none")
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url=TEST_BASE_URL) as client:
        response = await client.get("/ready")

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
