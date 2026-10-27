from collections.abc import AsyncIterator, Sequence
from itertools import batched
from typing import Final, Literal, cast

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionChunk, ChatCompletionMessageParam

from chatbot_api.core.config import Settings
from chatbot_api.providers.base import ChatMessage
from chatbot_api.providers.errors import translate_provider_error
from chatbot_api.providers.profile import ProviderProfile

EMBEDDING_BATCH_SIZE = 64
EMBEDDING_ENCODING: Final[Literal["float"]] = "float"
INVALID_EMBEDDINGS_MESSAGE = "O provedor retornou embeddings inconsistentes."


class InvalidEmbeddingsError(RuntimeError):
    pass


def create_client(profile: ProviderProfile, settings: Settings) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=profile.base_url,
        api_key=profile.api_key.get_secret_value(),
        timeout=settings.provider_timeout_seconds,
        max_retries=settings.provider_max_retries,
    )


def _to_message_param(message: ChatMessage) -> ChatCompletionMessageParam:
    return cast(
        ChatCompletionMessageParam, {"role": message.role.value, "content": message.content}
    )


def _delta_text(chunk: ChatCompletionChunk) -> str:
    if not chunk.choices:
        return ""
    return chunk.choices[0].delta.content or ""


def _validate_embeddings(vectors: list[list[float]], expected_count: int) -> None:
    dimensions = {len(vector) for vector in vectors}
    if len(vectors) != expected_count or len(dimensions) != 1 or 0 in dimensions:
        raise InvalidEmbeddingsError(INVALID_EMBEDDINGS_MESSAGE)


class OpenAICompatibleProvider:
    """One adapter for any OpenAI-compatible endpoint: Ollama (dev) or the real provider (prod)."""

    def __init__(self, client: AsyncOpenAI, embedding_model: str) -> None:
        self._client = client
        self._embedding_model = embedding_model

    @property
    def embedding_model(self) -> str:
        return self._embedding_model

    async def stream_chat(
        self,
        *,
        model: str,
        messages: Sequence[ChatMessage],
        max_output_tokens: int,
    ) -> AsyncIterator[str]:
        try:
            stream = await self._client.chat.completions.create(
                model=model,
                messages=[_to_message_param(message) for message in messages],
                max_completion_tokens=max_output_tokens,
                stream=True,
            )
            async with stream:
                async for chunk in stream:
                    text = _delta_text(chunk)
                    if text:
                        yield text
        except openai.APIError as exc:
            raise translate_provider_error(exc) from exc

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for batch in batched(texts, EMBEDDING_BATCH_SIZE, strict=False):
            vectors.extend(await self._embed_batch(batch))
        _validate_embeddings(vectors, len(texts))
        return vectors

    async def _embed_batch(self, batch: Sequence[str]) -> list[list[float]]:
        try:
            response = await self._client.embeddings.create(
                model=self._embedding_model,
                input=list(batch),
                encoding_format=EMBEDDING_ENCODING,
            )
        except openai.APIError as exc:
            raise translate_provider_error(exc) from exc
        ordered = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in ordered]

    async def close(self) -> None:
        await self._client.close()
