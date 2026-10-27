from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = structlog.get_logger(__name__)

POOL_SIZE = 5
POOL_MAX_OVERFLOW = 5

SessionFactory = async_sessionmaker[AsyncSession]


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(
        database_url,
        pool_size=POOL_SIZE,
        max_overflow=POOL_MAX_OVERFLOW,
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(engine, expire_on_commit=False)


def database_readiness_check(engine: AsyncEngine) -> Callable[[], Awaitable[bool]]:
    async def check() -> bool:
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError) as exc:
            logger.warning("database_not_ready", error_class=type(exc).__name__)
            return False
        return True

    return check
