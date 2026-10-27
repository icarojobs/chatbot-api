import json
from collections.abc import Callable
from http import HTTPStatus

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI

from chatbot_api.core.errors import ApiError
from chatbot_api.providers.base import ChatMessage, ChatRole
from chatbot_api.providers.openai_compatible import (
    EMBEDDING_BATCH_SIZE,
    InvalidEmbeddingsError,
    OpenAICompatibleProvider,
)

Handler = Callable[[httpx.Request], httpx.Response]

EMBEDDING_MODEL = "embed-model"
CHAT_MODEL = "chat-model"
MESSAGES = [ChatMessage(ChatRole.USER, "Olá")]


def build_provider(handler: Handler) -> OpenAICompatibleProvider:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncOpenAI(
        base_url="http://provider.test/v1", api_key="key", max_retries=0, http_client=http_client
    )
    return OpenAICompatibleProvider(client, EMBEDDING_MODEL)


def sse_chunk(choices: list[dict[str, object]]) -> str:
    payload = {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": CHAT_MODEL,
        "choices": choices,
    }
    return f"data: {json.dumps(payload)}\n\n"


def text_choice(text: str | None) -> dict[str, object]:
    return {"index": 0, "delta": {"content": text}, "finish_reason": None}


def streaming_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    assert body["stream"] is True
    assert body["max_completion_tokens"] == 50
    assert body["messages"] == [{"role": "user", "content": "Olá"}]
    events = [
        sse_chunk([text_choice("")]),
        sse_chunk([text_choice("Olá")]),
        sse_chunk([]),
        sse_chunk([text_choice(None)]),
        sse_chunk([text_choice(", mundo")]),
        "data: [DONE]\n\n",
    ]
    return httpx.Response(
        HTTPStatus.OK, content="".join(events), headers={"content-type": "text/event-stream"}
    )


async def collect(provider: OpenAICompatibleProvider) -> list[str]:
    stream = provider.stream_chat(model=CHAT_MODEL, messages=MESSAGES, max_output_tokens=50)
    return [text async for text in stream]


async def test_streams_only_non_empty_text() -> None:
    provider = build_provider(streaming_handler)

    assert await collect(provider) == ["Olá", ", mundo"]
    await provider.close()


def embeddings_handler(dimension_by_text: dict[str, int] | None = None) -> Handler:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == EMBEDDING_MODEL
        assert body["encoding_format"] == "float"
        calls.append(len(body["input"]))
        dimensions = dimension_by_text or {}
        data = [
            {
                "object": "embedding",
                "index": index,
                "embedding": [float(index)] * dimensions.get(text, 3),
            }
            for index, text in reversed(list(enumerate(body["input"])))
        ]
        return httpx.Response(
            HTTPStatus.OK,
            json={
                "object": "list",
                "data": data,
                "model": EMBEDDING_MODEL,
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        )

    handler.calls = calls  # type: ignore[attr-defined]
    return handler


async def test_embeds_in_batches_preserving_order() -> None:
    handler = embeddings_handler()
    provider = build_provider(handler)
    texts = [f"texto {index}" for index in range(EMBEDDING_BATCH_SIZE + 1)]

    vectors = await provider.embed(texts)

    assert len(vectors) == len(texts)
    assert vectors[0] == [0.0, 0.0, 0.0]
    assert vectors[1] == [1.0, 1.0, 1.0]
    assert vectors[-1] == [0.0, 0.0, 0.0]
    assert handler.calls == [EMBEDDING_BATCH_SIZE, 1]  # type: ignore[attr-defined]
    assert provider.embedding_model == EMBEDDING_MODEL


async def test_rejects_inconsistent_dimensions() -> None:
    provider = build_provider(embeddings_handler({"b": 2}))

    with pytest.raises(InvalidEmbeddingsError):
        await provider.embed(["a", "b"])


def failing_handler(status: HTTPStatus) -> Handler:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "secret internals"}})

    return handler


def raising_handler(error: Exception) -> Handler:
    def handler(_: httpx.Request) -> httpx.Response:
        raise error

    return handler


@pytest.mark.parametrize(
    ("handler", "status", "code"),
    [
        (
            failing_handler(HTTPStatus.TOO_MANY_REQUESTS),
            HTTPStatus.SERVICE_UNAVAILABLE,
            "provider_rate_limited",
        ),
        (
            failing_handler(HTTPStatus.INTERNAL_SERVER_ERROR),
            HTTPStatus.BAD_GATEWAY,
            "provider_error",
        ),
        (
            raising_handler(httpx.ReadTimeout("slow")),
            HTTPStatus.GATEWAY_TIMEOUT,
            "provider_timeout",
        ),
        (
            raising_handler(httpx.ConnectError("down")),
            HTTPStatus.BAD_GATEWAY,
            "provider_unavailable",
        ),
    ],
)
async def test_translates_provider_errors(handler: Handler, status: HTTPStatus, code: str) -> None:
    provider = build_provider(handler)

    with pytest.raises(ApiError) as chat_error:
        await collect(provider)
    with pytest.raises(ApiError) as embed_error:
        await provider.embed(["a"])

    for error in (chat_error.value, embed_error.value):
        assert (error.status_code, error.code) == (status, code)
        assert "secret internals" not in error.message
