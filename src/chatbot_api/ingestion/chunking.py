import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from chatbot_api.ingestion.loaders import PageText

# ~375 tokens per chunk for Portuguese text (≈ 4 characters per token).
CHUNK_SIZE_CHARS = 1500
CHUNK_OVERLAP_CHARS = 200
SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?:;])\s+")


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    chunk_index: int
    page_start: int
    page_end: int
    content: str


@dataclass(frozen=True, slots=True)
class Sentence:
    page_number: int
    text: str


def _split_long(text: str, size: int) -> Iterator[str]:
    words = text.split(" ")
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > size and current:
            yield current
            candidate = word
        current = candidate
    if current:
        yield current


def _sentences(pages: Sequence[PageText], size: int) -> Iterator[Sentence]:
    for page in pages:
        for sentence in SENTENCE_BOUNDARY.split(page.text):
            for piece in _split_long(sentence, size):
                yield Sentence(page.page_number, piece)


def _overlap_tail(sentences: list[Sentence], overlap: int) -> list[Sentence]:
    tail: list[Sentence] = []
    length = 0
    for sentence in reversed(sentences[1:]):
        length += len(sentence.text) + 1
        if length > overlap:
            break
        tail.insert(0, sentence)
    return tail


def _to_draft(index: int, sentences: list[Sentence]) -> ChunkDraft:
    return ChunkDraft(
        chunk_index=index,
        page_start=sentences[0].page_number,
        page_end=sentences[-1].page_number,
        content=" ".join(sentence.text for sentence in sentences),
    )


def chunk_pages(
    pages: Sequence[PageText],
    size: int = CHUNK_SIZE_CHARS,
    overlap: int = CHUNK_OVERLAP_CHARS,
) -> list[ChunkDraft]:
    """Packs whole sentences into chunks (may cross pages); trailing sentences become overlap."""
    drafts: list[ChunkDraft] = []
    current: list[Sentence] = []
    length = 0
    for sentence in _sentences(pages, size):
        if current and length + len(sentence.text) + 1 > size:
            drafts.append(_to_draft(len(drafts), current))
            current = _overlap_tail(current, overlap)
            length = sum(len(item.text) + 1 for item in current)
        current.append(sentence)
        length += len(sentence.text) + 1
    if current:
        drafts.append(_to_draft(len(drafts), current))
    return drafts
