from collections.abc import Sequence

from chatbot_api.rag.retrieval import RetrievedChunk


def select_context(
    chunks: Sequence[RetrievedChunk], min_score: float, max_chars: int
) -> list[RetrievedChunk]:
    """Keeps chunks above the calibrated similarity floor, best first, within the context budget.

    An empty result means the knowledge base has no sufficient evidence and the answer abstains.
    """
    selected: list[RetrievedChunk] = []
    used_chars = 0
    for chunk in sorted(chunks, key=lambda item: item.score, reverse=True):
        if chunk.score < min_score:
            break
        if used_chars + len(chunk.content) > max_chars:
            break
        selected.append(chunk)
        used_chars += len(chunk.content)
    return selected
