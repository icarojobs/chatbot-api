from pathlib import Path

import pytest
from pydantic import ValidationError

from chatbot_api.core.config import Environment, Settings, get_settings
from tests.conftest import ACCESS_TOKEN, ADMIN_TOKEN, SettingsFactory


def test_defaults_to_development(settings: Settings) -> None:
    assert settings.api_env is Environment.DEVELOPMENT
    assert settings.is_production is False


def test_production_flag(settings_factory: SettingsFactory) -> None:
    settings = settings_factory(
        api_env="production",
        openai_base_url="https://provider.test/v1",
        openai_access_key="key",
        openai_response_models="m1",
        openai_embeddings_models="e1",
    )

    assert settings.is_production is True


def test_splits_comma_separated_models(settings_factory: SettingsFactory) -> None:
    settings = settings_factory(
        openai_response_models=" azure/gpt-5-mini, azure/gpt-6-luna ,",
        openai_embeddings_models="cohere/embed-v4.0",
    )

    assert settings.openai_response_models == ("azure/gpt-5-mini", "azure/gpt-6-luna")
    assert settings.openai_embeddings_models == ("cohere/embed-v4.0",)


def test_accepts_model_sequences(settings_factory: SettingsFactory) -> None:
    settings = settings_factory(openai_response_models=["model-a"])

    assert settings.openai_response_models == ("model-a",)


def test_rejects_short_tokens(settings_factory: SettingsFactory) -> None:
    with pytest.raises(ValidationError):
        settings_factory(api_access_token="short")


def test_reads_environment_variables(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/app")
    monkeypatch.setenv("API_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("API_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("OPENAI_RESPONSE_MODELS", "m1,m2")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.openai_response_models == ("m1", "m2")
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("api_env", "enabled", "allowed"),
    [
        ("development", None, True),
        ("production", None, False),
        ("production", True, True),
        ("development", False, False),
    ],
)
def test_documents_reset_is_disabled_in_production_by_default(
    settings_factory: SettingsFactory, api_env: str, enabled: bool | None, allowed: bool
) -> None:
    provider = {
        "openai_base_url": "https://provider.test/v1",
        "openai_access_key": "key",
        "openai_response_models": "azure/gpt-5-mini",
        "openai_embeddings_models": "cohere/embed-v4.0",
    }
    settings = settings_factory(api_env=api_env, documents_reset_enabled=enabled, **provider)

    assert settings.documents_reset_allowed is allowed


def test_cors_allows_any_origin_by_default(settings: Settings) -> None:
    assert settings.cors_allowed_origins == ("*",)


def test_splits_comma_separated_cors_origins(settings_factory: SettingsFactory) -> None:
    settings = settings_factory(cors_allowed_origins="https://a.example.com, http://localhost:5500")

    assert settings.cors_allowed_origins == ("https://a.example.com", "http://localhost:5500")
