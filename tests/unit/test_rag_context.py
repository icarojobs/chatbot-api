import uuid

from chatbot_api.providers.base import ChatRole
from chatbot_api.rag.context import select_context
from chatbot_api.rag.prompting import SYSTEM_PROMPT, build_messages, format_pages
from chatbot_api.rag.retrieval import RetrievedChunk


def chunk(score: float, content: str = "texto", pages: tuple[int, int] = (1, 1)) -> RetrievedChunk:
    return RetrievedChunk(uuid.uuid4(), uuid.uuid4(), "apostila.pdf", *pages, content, score)


def test_keeps_chunks_above_threshold_best_first() -> None:
    selected = select_context([chunk(0.5), chunk(0.9), chunk(0.2)], min_score=0.4, max_chars=100)

    assert [item.score for item in selected] == [0.9, 0.5]


def test_no_chunk_above_threshold_means_insufficient_context() -> None:
    assert select_context([chunk(0.3), chunk(0.1)], min_score=0.47, max_chars=100) == []


def test_respects_context_budget() -> None:
    chunks = [chunk(0.9, "a" * 60), chunk(0.8, "b" * 60)]

    assert len(select_context(chunks, min_score=0.1, max_chars=100)) == 1


def test_formats_single_page_and_ranges() -> None:
    assert format_pages(chunk(1, pages=(3, 3))) == "p. 3"
    assert format_pages(chunk(1, pages=(3, 5))) == "p. 3-5"


def test_builds_messages_with_numbered_sources() -> None:
    messages = build_messages(
        "O que é matriciamento?", [chunk(0.9, "Primeiro"), chunk(0.8, "Segundo", (2, 3))]
    )

    assert messages[0].role is ChatRole.SYSTEM
    assert messages[0].content == SYSTEM_PROMPT
    assert messages[1].role is ChatRole.USER
    assert "[1] apostila.pdf (p. 1)\nPrimeiro" in messages[1].content
    assert "[2] apostila.pdf (p. 2-3)\nSegundo" in messages[1].content
    assert messages[1].content.endswith("PERGUNTA:\nO que é matriciamento?")
