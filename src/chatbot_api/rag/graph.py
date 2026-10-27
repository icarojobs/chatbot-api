from dataclasses import dataclass
from typing import Literal, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from chatbot_api.providers.base import ChatModelProvider, EmbeddingProvider
from chatbot_api.rag.context import select_context
from chatbot_api.rag.prompting import ABSTENTION_MESSAGE, build_messages
from chatbot_api.rag.retrieval import RetrievedChunk, Retriever

STREAM_TEXT_KEY = "text"


class RAGState(TypedDict, total=False):
    question: str
    instructions: str
    model: str
    top_k: int
    query_embedding: list[float]
    candidates: list[RetrievedChunk]
    context: list[RetrievedChunk]
    answer: str
    abstained: bool


@dataclass(frozen=True, slots=True)
class RAGSettings:
    min_score: float
    context_max_chars: int
    max_output_tokens: int


class RAGNodes:
    """Graph nodes with injected dependencies; each one returns only the state it changes."""

    def __init__(
        self,
        embedder: EmbeddingProvider,
        chat: ChatModelProvider,
        retriever: Retriever,
        settings: RAGSettings,
    ) -> None:
        self._embedder = embedder
        self._chat = chat
        self._retriever = retriever
        self._settings = settings

    async def validate_input(self, state: RAGState) -> RAGState:
        return {"question": " ".join(state["question"].split())}

    async def embed_question(self, state: RAGState) -> RAGState:
        [vector] = await self._embedder.embed([state["question"]])
        return {"query_embedding": vector}

    async def retrieve_context(self, state: RAGState) -> RAGState:
        candidates = await self._retriever.search(
            state["query_embedding"], self._embedder.embedding_model, state["top_k"]
        )
        return {"candidates": candidates}

    async def evaluate_context(self, state: RAGState) -> RAGState:
        context = select_context(
            state["candidates"], self._settings.min_score, self._settings.context_max_chars
        )
        return {"context": context}

    async def generate_answer(self, state: RAGState) -> RAGState:
        write = get_stream_writer()
        parts: list[str] = []
        stream = self._chat.stream_chat(
            model=state["model"],
            messages=build_messages(
                state["question"], state["context"], state.get("instructions", "")
            ),
            max_output_tokens=self._settings.max_output_tokens,
        )
        async for text in stream:
            parts.append(text)
            write({STREAM_TEXT_KEY: text})
        return {"answer": "".join(parts), "abstained": False}

    async def abstain(self, state: RAGState) -> RAGState:
        get_stream_writer()({STREAM_TEXT_KEY: ABSTENTION_MESSAGE})
        return {"answer": ABSTENTION_MESSAGE, "abstained": True, "context": []}


def route_after_evaluation(state: RAGState) -> Literal["generate_answer", "abstain"]:
    return "generate_answer" if state["context"] else "abstain"


def build_rag_graph(nodes: RAGNodes) -> CompiledStateGraph[RAGState, None, RAGState, RAGState]:
    builder = StateGraph(RAGState)
    builder.add_node("validate_input", nodes.validate_input)
    builder.add_node("embed_question", nodes.embed_question)
    builder.add_node("retrieve_context", nodes.retrieve_context)
    builder.add_node("evaluate_context", nodes.evaluate_context)
    builder.add_node("generate_answer", nodes.generate_answer)
    builder.add_node("abstain", nodes.abstain)

    builder.add_edge(START, "validate_input")
    builder.add_edge("validate_input", "embed_question")
    builder.add_edge("embed_question", "retrieve_context")
    builder.add_edge("retrieve_context", "evaluate_context")
    builder.add_conditional_edges("evaluate_context", route_after_evaluation)
    builder.add_edge("generate_answer", END)
    builder.add_edge("abstain", END)
    return builder.compile()
