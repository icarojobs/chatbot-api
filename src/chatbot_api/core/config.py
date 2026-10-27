from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LIST_SEPARATOR = ","
MIN_TOKEN_LENGTH = 32
MISSING_PRODUCTION_PROVIDER = (
    "API_ENV=production exige OPENAI_BASE_URL, OPENAI_ACCESS_KEY, "
    "OPENAI_RESPONSE_MODELS e OPENAI_EMBEDDINGS_MODELS."
)

ModelList = Annotated[tuple[str, ...], NoDecode]


class Environment(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    api_env: Environment = Environment.DEVELOPMENT
    app_name: str = "chatbot-api"
    log_level: str = "INFO"

    database_url: SecretStr

    api_access_token: SecretStr = Field(min_length=MIN_TOKEN_LENGTH)
    api_admin_token: SecretStr = Field(min_length=MIN_TOKEN_LENGTH)

    rate_limit_default: str = "60/minute"
    trusted_proxy_hops: int = Field(default=0, ge=0)

    openai_base_url: str = ""
    openai_access_key: SecretStr = SecretStr("")
    openai_response_models: ModelList = ()
    openai_embeddings_models: ModelList = ()

    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_access_key: SecretStr = SecretStr("ollama")
    ollama_response_models: ModelList = ("qwen3:4b-instruct-2507-q4_K_M",)
    ollama_embeddings_models: ModelList = ("bge-m3:567m",)

    provider_timeout_seconds: float = Field(default=120.0, gt=0)
    provider_max_retries: int = Field(default=1, ge=0)
    llm_max_output_tokens: int = Field(default=1500, gt=0)

    rag_top_k_default: int = Field(default=4, ge=1)
    rag_top_k_max: int = Field(default=8, ge=1)
    rag_min_score: float | None = Field(default=None, ge=0, le=1)
    rag_context_max_chars: int = Field(default=18000, gt=0)

    upload_max_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    upload_ttl_minutes: int = Field(default=60, gt=0)
    direct_upload_max_bytes: int = Field(default=30 * 1024 * 1024, gt=0)
    documents_reset_enabled: bool | None = None

    @field_validator(
        "openai_response_models",
        "openai_embeddings_models",
        "ollama_response_models",
        "ollama_embeddings_models",
        mode="before",
    )
    @classmethod
    def split_models(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return tuple(item.strip() for item in value.split(LIST_SEPARATOR) if item.strip())

    @model_validator(mode="after")
    def require_production_provider(self) -> Self:
        if not self.is_production:
            return self
        required = (
            self.openai_base_url,
            self.openai_access_key.get_secret_value(),
            self.openai_response_models,
            self.openai_embeddings_models,
        )
        if not all(required):
            raise ValueError(MISSING_PRODUCTION_PROVIDER)
        return self

    @property
    def is_production(self) -> bool:
        return self.api_env is Environment.PRODUCTION

    @property
    def documents_reset_allowed(self) -> bool:
        if self.documents_reset_enabled is None:
            return not self.is_production
        return self.documents_reset_enabled


@lru_cache
def get_settings() -> Settings:
    return Settings()
