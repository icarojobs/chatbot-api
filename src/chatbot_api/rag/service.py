import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from langgraph.graph.state import CompiledStateGraph

from chatbot_api.rag.graph import STREAM_TEXT_KEY, RAGState
from chatbot_api.rag.retrieval import RetrievedChunk

CUSTOM_MODE: Final[Literal["custom"]] = "custom"
VALUES_MODE: Final[Literal["values"]] = "values"


@dataclass(frozen=True, slots=True)
class Source:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_start: int
    page_end: int
    score: float


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class AnswerCompleted:
    sources: list[Source]
    abstained: bool


RAGEvent = TextDelta | AnswerCompleted


def to_sources(chunks: Sequence[RetrievedChunk]) -> list[Source]:
    return [
        Source(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            filename=chunk.filename,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            score=round(chunk.score, 4),
        )
        for chunk in chunks
    ]


class RAGService:
    """Adapts the graph to a stable public event stream; internal graph state never leaks out."""

    def __init__(self, graph: CompiledStateGraph[RAGState, None, RAGState, RAGState]) -> None:
        self._graph = graph

    async def stream(
        self, question: str, model: str, top_k: int, instructions: str = ""
    ) -> AsyncIterator[RAGEvent]:
        final_state: RAGState = {}
        initial: RAGState = {
            "question": question,
            "instructions": instructions,
            "model": model,
            "top_k": top_k,
        }
        async for mode, payload in self._graph.astream(
            initial, stream_mode=[CUSTOM_MODE, VALUES_MODE]
        ):
            if mode == CUSTOM_MODE:
                yield TextDelta(_token_text(payload))
            else:
                final_state = cast(RAGState, payload)
        yield AnswerCompleted(
            sources=to_sources(final_state.get("context", [])),
            abstained=final_state.get("abstained", False),
        )


def _token_text(payload: Any) -> str:
    text: str = payload[STREAM_TEXT_KEY]
    return text
