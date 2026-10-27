from fastapi import FastAPI

from chatbot_api.api.routes import health
from chatbot_api.core.config import Settings, get_settings
from chatbot_api.core.errors import register_error_handlers
from chatbot_api.core.logging import RequestContextMiddleware, configure_logging
from chatbot_api.core.rate_limit import RateLimiter, RateLimitMiddleware

API_TITLE = "ChatBot API"
API_DESCRIPTION = (
    "API de chatbot com RAG sobre uma base de conhecimento prévia, "
    "compatível com o formato da API da OpenAI."
)
API_VERSION = "0.1.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    app = FastAPI(title=API_TITLE, description=API_DESCRIPTION, version=API_VERSION)
    app.state.settings = resolved_settings
    app.state.readiness_checks = []

    register_error_handlers(app)
    app.add_middleware(
        RateLimitMiddleware,
        limiter=RateLimiter(resolved_settings.rate_limit_default),
        trusted_proxy_hops=resolved_settings.trusted_proxy_hops,
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router)
    return app
