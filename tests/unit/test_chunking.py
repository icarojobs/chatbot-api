import itertools

from chatbot_api.ingestion.chunking import chunk_pages
from chatbot_api.ingestion.loaders import PageText


def sentence(number: int, length: int = 50) -> str:
    body = f"Frase número {number} "
    return body + "x" * (length - len(body) - 1) + "."


def test_empty_pages_produce_no_chunks() -> None:
    assert chunk_pages([PageText(1, ""), PageText(2, "")]) == []


def test_small_document_is_a_single_chunk() -> None:
    chunks = chunk_pages([PageText(1, "Primeira frase. Segunda frase.")])

    assert len(chunks) == 1
    assert chunks[0].content == "Primeira frase. Segunda frase."
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 1)


def test_chunks_respect_size_and_track_pages() -> None:
    pages = [
        PageText(page, " ".join(sentence(page * 10 + i) for i in range(4))) for page in (1, 2, 3)
    ]

    chunks = chunk_pages(pages, size=220, overlap=60)

    assert all(len(chunk.content) <= 220 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 3
    assert any(chunk.page_start != chunk.page_end for chunk in chunks)


def test_consecutive_chunks_overlap_by_whole_sentences() -> None:
    pages = [PageText(1, " ".join(sentence(i) for i in range(10)))]

    chunks = chunk_pages(pages, size=220, overlap=60)

    for previous, current in itertools.pairwise(chunks):
        last_sentence = previous.content.split(" Frase")[-1]
        assert current.content.startswith("Frase" + last_sentence)


def test_splits_sentences_longer_than_chunk_size() -> None:
    long_sentence = " ".join(["palavra"] * 100)

    chunks = chunk_pages([PageText(1, long_sentence)], size=100, overlap=0)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 100 for chunk in chunks)
    assert " ".join(chunk.content for chunk in chunks) == long_sentence
