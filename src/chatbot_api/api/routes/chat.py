import json
import time
import uuid
from collections.abc import AsyncIterator
from http import HTTPStatus
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from chatbot_api.core.config import Settings
from chatbot_api.core.errors import ApiError, ErrorType
from chatbot_api.core.security import require_access_token
from chatbot_api.providers.profile import ProviderProfile
from chatbot_api.rag.service import AnswerCompleted, RAGEvent, RAGService, Source, TextDelta

logger = structlog.get_logger(__name__)

QUESTION_MAX_CHARS = 4000
COMPLETION_ID_PREFIX = "chatcmpl-"
FINISH_REASON = "stop"
ASSISTANT_ROLE = "assistant"
SSE_DONE = "data: [DONE]\n\n"
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
SSE_MEDIA_TYPE = "text/event-stream"
STREAM_FAILED_MESSAGE = "A geração da resposta foi interrompida por um erro. Tente novamente."

NO_USER_MESSAGE = "A conversa precisa terminar com uma mensagem do usuário com texto."
QUESTION_TOO_LONG = f"A pergunta excede {QUESTION_MAX_CHARS} caracteres."
UNSUPPORTED_PARAMETER = "O parâmetro '{name}' não é suportado por esta API."
UNSUPPORTED_PARAMETERS = ("tools", "functions", "tool_choice", "function_call", "logprobs")

router = APIRouter(prefix="/v1", tags=["Chat"], dependencies=[Depends(require_access_token)])


class TextContentPart(BaseModel):
    type: Literal["text"]
    text: str


class ChatCompletionMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[TextContentPart] | None = None

    def text(self) -> str:
        if isinstance(self.content, list):
            return " ".join(part.text for part in self.content)
        return self.content or ""


class ChatCompletionRequest(BaseModel):
    """Subset of the OpenAI Chat Completions request; unknown fields are ignored, as in OpenAI."""

    model_config = ConfigDict(extra="allow")

    model: str | None = Field(default=None, examples=["azure/gpt-5-mini"])
    messages: list[ChatCompletionMessage] = Field(min_length=1)
    stream: bool = False
    n: int = Field(default=1, ge=1, le=1)
    top_k: int | None = Field(default=None, ge=1, description="Extensão: trechos a recuperar.")


class SourceModel(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_start: int
    page_end: int
    score: float


def _source_models(sources: list[Source]) -> list[dict[str, Any]]:
    return [
        SourceModel.model_validate(source, from_attributes=True).model_dump(mode="json")
        for source in sources
    ]


def extract_question(request: ChatCompletionRequest) -> str:
    rejected = [name for name in UNSUPPORTED_PARAMETERS if (request.model_extra or {}).get(name)]
    if rejected:
        raise _invalid(UNSUPPORTED_PARAMETER.format(name=rejected[0]), "unsupported_parameter")
    last = request.messages[-1]
    question = last.text().strip()
    if last.role != "user" or not question:
        raise _invalid(NO_USER_MESSAGE, "invalid_messages")
    if len(question) > QUESTION_MAX_CHARS:
        raise _invalid(QUESTION_TOO_LONG, "question_too_long")
    return question


def _invalid(message: str, code: str) -> ApiError:
    return ApiError(HTTPStatus.BAD_REQUEST, message, ErrorType.INVALID_REQUEST, code)


class CompletionFormatter:
    """OpenAI-compatible payloads; `sources` and `abstained` are extras clients may ignore."""

    def __init__(self, model: str) -> None:
        self.id = f"{COMPLETION_ID_PREFIX}{uuid.uuid4().hex}"
        self.created = int(time.time())
        self.model = model

    def _base(self, kind: str) -> dict[str, Any]:
        return {"id": self.id, "object": kind, "created": self.created, "model": self.model}

    def chunk(self, delta: dict[str, str], finish_reason: str | None = None) -> str:
        payload = self._base("chat.completion.chunk")
        payload["choices"] = [{"index": 0, "delta": delta, "finish_reason": finish_reason}]
        return _sse(payload)

    def final_chunk(self, completed: AnswerCompleted) -> str:
        payload = self._base("chat.completion.chunk")
        payload["choices"] = [{"index": 0, "delta": {}, "finish_reason": FINISH_REASON}]
        payload["sources"] = _source_models(completed.sources)
        payload["abstained"] = completed.abstained
        return _sse(payload)

    def completion(self, answer: str, completed: AnswerCompleted) -> dict[str, Any]:
        payload = self._base("chat.completion")
        payload["choices"] = [
            {
                "index": 0,
                "message": {"role": ASSISTANT_ROLE, "content": answer},
                "finish_reason": FINISH_REASON,
            }
        ]
        payload["sources"] = _source_models(completed.sources)
        payload["abstained"] = completed.abstained
        return payload


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _error_event(error: ApiError) -> str:
    return _sse(
        {
            "error": {
                "message": error.message,
                "type": error.error_type,
                "param": None,
                "code": error.code,
            }
        }
    )


async def stream_completion(
    first: RAGEvent, events: AsyncIterator[RAGEvent], formatter: CompletionFormatter
) -> AsyncIterator[str]:
    yield formatter.chunk({"role": ASSISTANT_ROLE, "content": ""})
    try:
        async for event in _prepend(first, events):
            if isinstance(event, TextDelta):
                yield formatter.chunk({"content": event.text})
            else:
                yield formatter.final_chunk(event)
    except ApiError as error:
        yield _error_event(error)
        return
    except Exception:
        logger.exception("stream_failed")
        yield _error_event(
            ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, STREAM_FAILED_MESSAGE, ErrorType.SERVER)
        )
        return
    yield SSE_DONE


async def _prepend(first: RAGEvent, events: AsyncIterator[RAGEvent]) -> AsyncIterator[RAGEvent]:
    yield first
    async for event in events:
        yield event


async def collect_completion(
    first: RAGEvent, events: AsyncIterator[RAGEvent], formatter: CompletionFormatter
) -> dict[str, Any]:
    parts: list[str] = []
    async for event in _prepend(first, events):
        if isinstance(event, TextDelta):
            parts.append(event.text)
            continue
        return formatter.completion("".join(parts), event)
    raise RuntimeError("RAG stream ended without completion")  # pragma: no cover


def get_rag_service(request: Request) -> RAGService:
    service: RAGService = request.app.state.rag_service
    return service


Rag = Annotated[RAGService, Depends(get_rag_service)]


@router.post(
    "/chat/completions",
    summary="Responde perguntas com base nas apostilas (formato da API da OpenAI)",
    response_model=None,
)
async def create_chat_completion(
    payload: ChatCompletionRequest, request: Request, rag: Rag
) -> StreamingResponse | dict[str, Any]:
    settings: Settings = request.app.state.settings
    profile: ProviderProfile = request.app.state.provider_profile
    question = extract_question(payload)
    model = profile.resolve_chat_model(payload.model)
    top_k = min(payload.top_k or settings.rag_top_k_default, settings.rag_top_k_max)

    events = aiter(rag.stream(question, model, top_k))
    first = await anext(events)
    formatter = CompletionFormatter(model)
    if not payload.stream:
        return await collect_completion(first, events, formatter)
    return StreamingResponse(
        stream_completion(first, events, formatter), media_type=SSE_MEDIA_TYPE, headers=SSE_HEADERS
    )
