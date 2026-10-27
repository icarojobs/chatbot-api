from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LIST_SEPARATOR = ","
MIN_TOKEN_LENGTH = 32

ModelList = Annotated[tuple[str, ...], NoDecode]


class Environment(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    api_env: Environment = Environment.DEVELOPMENT
    app_name: str = "chatbot-api"
    log_level: str = "INFO"

    api_access_token: SecretStr = Field(min_length=MIN_TOKEN_LENGTH)
    api_admin_token: SecretStr = Field(min_length=MIN_TOKEN_LENGTH)

    rate_limit_default: str = "60/minute"
    trusted_proxy_hops: int = Field(default=0, ge=0)

    openai_base_url: str = ""
    openai_access_key: SecretStr = SecretStr("")
    openai_response_models: ModelList = ()
    openai_embeddings_models: ModelList = ()

    @field_validator("openai_response_models", "openai_embeddings_models", mode="before")
    @classmethod
    def split_models(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return tuple(item.strip() for item in value.split(LIST_SEPARATOR) if item.strip())

    @property
    def is_production(self) -> bool:
        return self.api_env is Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    return Settings()
