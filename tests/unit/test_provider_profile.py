from http import HTTPStatus

import pytest
from pydantic import ValidationError

from chatbot_api.core.errors import ApiError
from chatbot_api.providers.profile import FALLBACK_MIN_SCORE, ModelType, build_provider_profile
from tests.conftest import SettingsFactory

PRODUCTION_PROVIDER = {
    "api_env": "production",
    "openai_base_url": "https://provider.test/v1",
    "openai_access_key": "real-key",
    "openai_response_models": "azure/gpt-5-mini,azure/gpt-6-luna",
    "openai_embeddings_models": "cohere/embed-v4.0",
}


def test_development_uses_ollama(settings_factory: SettingsFactory) -> None:
    profile = build_provider_profile(settings_factory())

    assert profile.base_url == "http://localhost:11434/v1"
    assert profile.chat_models == ("qwen3:4b-instruct-2507-q4_K_M",)
    assert profile.embedding_model == "bge-m3:567m"


def test_production_uses_real_provider(settings_factory: SettingsFactory) -> None:
    profile = build_provider_profile(settings_factory(**PRODUCTION_PROVIDER))

    assert profile.base_url == "https://provider.test/v1"
    assert profile.api_key.get_secret_value() == "real-key"
    assert profile.chat_models == ("azure/gpt-5-mini", "azure/gpt-6-luna")
    assert profile.embedding_model == "cohere/embed-v4.0"


@pytest.mark.parametrize("missing", list(PRODUCTION_PROVIDER)[1:])
def test_production_requires_provider_settings(
    settings_factory: SettingsFactory, missing: str
) -> None:
    with pytest.raises(ValidationError, match="API_ENV=production exige"):
        settings_factory(**{**PRODUCTION_PROVIDER, missing: ""})


def test_resolves_default_and_allowed_models(settings_factory: SettingsFactory) -> None:
    profile = build_provider_profile(settings_factory(**PRODUCTION_PROVIDER))

    assert profile.resolve_chat_model(None) == "azure/gpt-5-mini"
    assert profile.resolve_chat_model("azure/gpt-6-luna") == "azure/gpt-6-luna"


def test_rejects_unknown_model(settings_factory: SettingsFactory) -> None:
    profile = build_provider_profile(settings_factory())

    with pytest.raises(ApiError) as error:
        profile.resolve_chat_model("gpt-4o")

    assert error.value.status_code == HTTPStatus.NOT_FOUND
    assert error.value.code == "model_not_found"


def test_rejects_embedding_model_for_chat(settings_factory: SettingsFactory) -> None:
    profile = build_provider_profile(settings_factory(**PRODUCTION_PROVIDER))

    with pytest.raises(ApiError) as error:
        profile.resolve_chat_model("cohere/embed-v4.0")

    assert error.value.status_code == HTTPStatus.BAD_REQUEST
    assert error.value.code == "invalid_model_type"


def test_models_are_typed_by_purpose(settings_factory: SettingsFactory) -> None:
    profile = build_provider_profile(settings_factory(**PRODUCTION_PROVIDER))

    assert profile.models == {
        "azure/gpt-5-mini": ModelType.CHAT,
        "azure/gpt-6-luna": ModelType.CHAT,
        "cohere/embed-v4.0": ModelType.EMBEDDING,
    }


def test_min_score_is_calibrated_per_embedding_model(settings_factory: SettingsFactory) -> None:
    assert build_provider_profile(settings_factory()).min_score == 0.47
    assert build_provider_profile(settings_factory(**PRODUCTION_PROVIDER)).min_score == 0.27


def test_unknown_embedding_model_uses_fallback(settings_factory: SettingsFactory) -> None:
    settings = settings_factory(ollama_embeddings_models="nomic-embed-text")

    assert build_provider_profile(settings).min_score == FALLBACK_MIN_SCORE


def test_explicit_min_score_overrides_calibration(settings_factory: SettingsFactory) -> None:
    assert build_provider_profile(settings_factory(rag_min_score=0.6)).min_score == 0.6
