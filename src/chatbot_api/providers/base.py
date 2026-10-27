from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ChatRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: ChatRole
    content: str


class ChatModelProvider(Protocol):
    def stream_chat(
        self,
        *,
        model: str,
        messages: Sequence[ChatMessage],
        max_output_tokens: int,
    ) -> AsyncIterator[str]: ...


class EmbeddingProvider(Protocol):
    @property
    def embedding_model(self) -> str: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
