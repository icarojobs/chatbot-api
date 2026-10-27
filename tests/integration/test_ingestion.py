import uuid

import pytest
from sqlalchemy import func, select

from chatbot_api.db.models import Chunk, ChunkEmbedding, Document, DocumentStatus
from chatbot_api.db.session import SessionFactory
from chatbot_api.ingestion.loaders import InvalidDocumentError
from chatbot_api.ingestion.pipeline import IngestionService
from tests.fakes import FakeEmbeddingProvider, build_pdf

LONG_PAGE = " ".join(
    f"Frase {index} sobre cuidado em saúde mental na atenção primária." for index in range(40)
)
PDF = build_pdf([LONG_PAGE, LONG_PAGE.replace("Frase", "Sentença")])


async def count(session_factory: SessionFactory, model: type[object]) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model)) or 0


async def test_ingests_document_with_chunks_and_embeddings(session_factory: SessionFactory) -> None:
    service = IngestionService(session_factory, FakeEmbeddingProvider())

    result = await service.ingest("apostila.pdf", PDF)

    assert result.status is DocumentStatus.READY
    assert result.filename == "apostila.pdf"
    assert result.chunk_count > 1
    assert result.embedded_chunks == result.chunk_count
    assert await count(session_factory, ChunkEmbedding) == result.chunk_count
    async with session_factory() as session:
        pages = (await session.execute(select(Chunk.page_start, Chunk.page_end))).all()
    assert {page for row in pages for page in row} == {1, 2}


async def test_reingestion_is_idempotent(session_factory: SessionFactory) -> None:
    embedder = FakeEmbeddingProvider()
    service = IngestionService(session_factory, embedder)

    first = await service.ingest("apostila.pdf", PDF)
    second = await service.ingest("copia.pdf", PDF)

    assert second.document_id == first.document_id
    assert second.embedded_chunks == 0
    assert len(embedder.calls) == 1
    assert await count(session_factory, Document) == 1


async def test_failed_embedding_marks_document_and_retry_resumes(
    session_factory: SessionFactory,
) -> None:
    embedder = FakeEmbeddingProvider(fail=True)
    service = IngestionService(session_factory, embedder)

    with pytest.raises(RuntimeError):
        await service.ingest("apostila.pdf", PDF)

    async with session_factory() as session:
        document = await session.scalar(select(Document))
    assert document is not None
    assert document.status is DocumentStatus.FAILED
    assert document.error == "Falha ao gerar os embeddings do documento."
    assert await count(session_factory, Chunk) > 0

    embedder.fail = False
    result = await service.ingest("apostila.pdf", PDF)

    assert result.status is DocumentStatus.READY
    assert result.embedded_chunks == result.chunk_count


async def test_reingesting_ready_document_with_failing_provider_keeps_it_ready(
    session_factory: SessionFactory,
) -> None:
    embedder = FakeEmbeddingProvider()
    service = IngestionService(session_factory, embedder)
    await service.ingest("apostila.pdf", PDF)

    embedder.fail = True
    result = await service.ingest("apostila.pdf", PDF)

    assert result.status is DocumentStatus.READY
    assert result.embedded_chunks == 0


async def test_new_embedding_model_embeds_existing_chunks(session_factory: SessionFactory) -> None:
    first = await IngestionService(session_factory, FakeEmbeddingProvider()).ingest("a.pdf", PDF)

    second = await IngestionService(session_factory, FakeEmbeddingProvider("other-model")).ingest(
        "a.pdf", PDF
    )

    assert second.embedded_chunks == first.chunk_count
    assert await count(session_factory, ChunkEmbedding) == 2 * first.chunk_count


async def test_rejects_pdf_without_text(session_factory: SessionFactory) -> None:
    service = IngestionService(session_factory, FakeEmbeddingProvider())

    with pytest.raises(InvalidDocumentError, match="não contém texto"):
        await service.ingest("vazio.pdf", build_pdf(["", ""]))

    assert await count(session_factory, Document) == 0


async def test_embed_pending_unknown_document(session_factory: SessionFactory) -> None:
    service = IngestionService(session_factory, FakeEmbeddingProvider())

    with pytest.raises(LookupError):
        await service.embed_pending(uuid.uuid4())
