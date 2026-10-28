import importlib
import sys

import pytest
from fastapi import FastAPI

from chatbot_api.core.config import get_settings

ASGI_MODULE = "chatbot_api.asgi"
DATABASE_URL = "postgresql+psycopg://user:secret@db.example/chatbot"


async def test_module_exposes_an_app_built_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("API_ACCESS_TOKEN", "a" * 40)
    monkeypatch.setenv("API_ADMIN_TOKEN", "b" * 40)
    monkeypatch.delitem(sys.modules, ASGI_MODULE, raising=False)
    get_settings.cache_clear()

    try:
        app = importlib.import_module(ASGI_MODULE).app
        assert isinstance(app, FastAPI)
        assert app.state.settings.database_url.get_secret_value() == DATABASE_URL
        await app.state.engine.dispose()
    finally:
        get_settings.cache_clear()
