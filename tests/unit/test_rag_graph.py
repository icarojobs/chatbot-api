from collections.abc import Sequence
from http import HTTPStatus

import pytest

from chatbot_api.core.errors import ApiError, ErrorType
from chatbot_api.rag.graph import RAGNodes, RAGSettings, build_rag_graph, route_after_evaluation
from chatbot_api.rag.prompting import ABSTENTION_MESSAGE
from chatbot_api.rag.service import AnswerCompleted, RAGEvent, RAGService, TextDelta
from tests.fakes import DOCUMENT_ID, FakeChatProvider, FakeEmbeddingProvider, FakeRetriever

SETTINGS = RAGSettings(min_score=0.47, context_max_chars=18000, max_output_tokens=321)


def build_service(
    scores: Sequence[float], chat: FakeChatProvider
) -> tuple[RAGService, FakeRetriever]:
    retriever = FakeRetriever(scores)
    nodes = RAGNodes(FakeEmbeddingProvider(), chat, retriever, SETTINGS)
    return RAGService(build_rag_graph(nodes)), retriever


async def collect(
    service: RAGService, question: str = "  O que é   saúde mental? "
) -> list[RAGEvent]:
    return [event async for event in service.stream(question, "chat-model", 3)]


async def test_answers_with_streamed_tokens_and_sources() -> None:
    chat = FakeChatProvider()
    service, retriever = build_service([0.9, 0.6, 0.2], chat)

    events = await collect(service)

    assert [event.text for event in events if isinstance(event, TextDelta)] == chat.tokens
    completed = events[-1]
    assert isinstance(completed, AnswerCompleted)
    assert completed.abstained is False
    assert [source.score for source in completed.sources] == [0.9, 0.6]
    assert completed.sources[0].filename == "apostila.pdf"
    assert completed.sources[0].document_id == DOCUMENT_ID
    assert retriever.calls == [("fake-embedding", 3)]
    model, messages, max_tokens = chat.calls[0]
    assert (model, max_tokens) == ("chat-model", 321)
    assert messages[1].content.endswith("PERGUNTA:\nO que é saúde mental?")


async def test_abstains_without_calling_the_llm_when_context_is_insufficient() -> None:
    chat = FakeChatProvider()
    service, _ = build_service([0.3, 0.1], chat)

    events = await collect(service)

    assert events[:-1] == [TextDelta(ABSTENTION_MESSAGE)]
    completed = events[-1]
    assert isinstance(completed, AnswerCompleted)
    assert completed.abstained is True
    assert completed.sources == []
    assert chat.calls == []


async def test_provider_errors_propagate() -> None:
    chat = FakeChatProvider()
    chat.error = ApiError(HTTPStatus.BAD_GATEWAY, "falha", ErrorType.SERVER, "provider_error")
    service, _ = build_service([0.9], chat)

    with pytest.raises(ApiError):
        await collect(service)


@pytest.mark.parametrize(("context", "route"), [([object()], "generate_answer"), ([], "abstain")])
def test_routes_after_evaluation(context: list[object], route: str) -> None:
    assert route_after_evaluation({"context": context}) == route  # type: ignore[typeddict-item]
