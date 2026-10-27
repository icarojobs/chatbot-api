from dataclasses import dataclass
from http import HTTPStatus

from pydantic import SecretStr

from chatbot_api.core.config import Settings
from chatbot_api.core.errors import ApiError, ErrorType

# Similarity floors calibrated with evaluation/questions.json (ADR-0006): each embedding model
# has its own score distribution, so a single global threshold would be wrong for one of them.
CALIBRATED_MIN_SCORES = {"bge-m3:567m": 0.47, "cohere/embed-v4.0": 0.27}
FALLBACK_MIN_SCORE = 0.3

MODEL_NOT_FOUND_MESSAGE = "O modelo '{model}' não existe ou não está disponível."
MODEL_NOT_FOUND_CODE = "model_not_found"


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    base_url: str
    api_key: SecretStr
    chat_models: tuple[str, ...]
    embedding_model: str
    min_score: float

    @property
    def default_chat_model(self) -> str:
        return self.chat_models[0]

    def resolve_chat_model(self, requested: str | None) -> str:
        if requested is None:
            return self.default_chat_model
        if requested in self.chat_models:
            return requested
        raise ApiError(
            HTTPStatus.NOT_FOUND,
            MODEL_NOT_FOUND_MESSAGE.format(model=requested),
            ErrorType.NOT_FOUND,
            MODEL_NOT_FOUND_CODE,
        )


def resolve_min_score(settings: Settings, embedding_model: str) -> float:
    if settings.rag_min_score is not None:
        return settings.rag_min_score
    return CALIBRATED_MIN_SCORES.get(embedding_model, FALLBACK_MIN_SCORE)


def build_provider_profile(settings: Settings) -> ProviderProfile:
    if settings.is_production:
        base_url, api_key = settings.openai_base_url, settings.openai_access_key
        chat_models, embedding_models = (
            settings.openai_response_models,
            settings.openai_embeddings_models,
        )
    else:
        base_url, api_key = settings.ollama_base_url, settings.ollama_access_key
        chat_models, embedding_models = (
            settings.ollama_response_models,
            settings.ollama_embeddings_models,
        )
    return ProviderProfile(
        base_url=base_url,
        api_key=api_key,
        chat_models=chat_models,
        embedding_model=embedding_models[0],
        min_score=resolve_min_score(settings, embedding_models[0]),
    )
