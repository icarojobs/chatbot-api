from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from chatbot_api.api.routes import documents, health, models
from chatbot_api.core.config import Settings, get_settings
from chatbot_api.core.errors import register_error_handlers
from chatbot_api.core.logging import RequestContextMiddleware, configure_logging
from chatbot_api.core.rate_limit import RateLimiter, RateLimitMiddleware
from chatbot_api.db.session import (
    create_engine,
    create_session_factory,
    database_readiness_check,
)
from chatbot_api.providers.openai_compatible import OpenAICompatibleProvider, create_client
from chatbot_api.providers.profile import build_provider_profile

API_TITLE = "ChatBot API"
API_DESCRIPTION = (
    "API de chatbot com RAG sobre uma base de conhecimento prévia, "
    "compatível com o formato da API da OpenAI."
)
API_VERSION = "0.1.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    profile = build_provider_profile(resolved_settings)
    engine = create_engine(resolved_settings.database_url.get_secret_value())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        provider = OpenAICompatibleProvider(
            create_client(profile, resolved_settings), profile.embedding_model
        )
        app.state.provider = provider
        try:
            yield
        finally:
            await provider.close()
            await engine.dispose()

    app = FastAPI(
        title=API_TITLE, description=API_DESCRIPTION, version=API_VERSION, lifespan=lifespan
    )
    app.state.settings = resolved_settings
    app.state.provider_profile = profile
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.readiness_checks = [database_readiness_check(engine)]

    register_error_handlers(app)
    app.add_middleware(
        RateLimitMiddleware,
        limiter=RateLimiter(resolved_settings.rate_limit_default),
        trusted_proxy_hops=resolved_settings.trusted_proxy_hops,
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router)
    app.include_router(models.router)
    app.include_router(documents.router)
    return app
