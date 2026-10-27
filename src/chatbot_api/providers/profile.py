from dataclasses import dataclass
from http import HTTPStatus

from pydantic import SecretStr

from chatbot_api.core.config import Settings
from chatbot_api.core.errors import ApiError, ErrorType

MODEL_NOT_FOUND_MESSAGE = "O modelo '{model}' não existe ou não está disponível."
MODEL_NOT_FOUND_CODE = "model_not_found"


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    base_url: str
    api_key: SecretStr
    chat_models: tuple[str, ...]
    embedding_model: str

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


def build_provider_profile(settings: Settings) -> ProviderProfile:
    if settings.is_production:
        return ProviderProfile(
            base_url=settings.openai_base_url,
            api_key=settings.openai_access_key,
            chat_models=settings.openai_response_models,
            embedding_model=settings.openai_embeddings_models[0],
        )
    return ProviderProfile(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_access_key,
        chat_models=settings.ollama_response_models,
        embedding_model=settings.ollama_embeddings_models[0],
    )
