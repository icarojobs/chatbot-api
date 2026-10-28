import asyncio

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from chatbot_api.db.models import Base

# Serializes concurrent upgrades (e.g. several instances or deploys starting at once).
MIGRATION_LOCK_ID = 727_001


def run_migrations(connection: Connection) -> None:
    connection.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": MIGRATION_LOCK_ID}
    )
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(context.config.attributes["database_url"], poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


asyncio.run(run_async_migrations())
