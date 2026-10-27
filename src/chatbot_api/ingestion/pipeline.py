import asyncio
import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from chatbot_api.db.models import Chunk, Document, DocumentStatus
from chatbot_api.db.repository import DocumentRepository
from chatbot_api.db.session import SessionFactory
from chatbot_api.ingestion.chunking import chunk_pages
from chatbot_api.ingestion.loaders import InvalidDocumentError, extract_pages
from chatbot_api.providers.base import EmbeddingProvider

logger = structlog.get_logger(__name__)

EMPTY_DOCUMENT_MESSAGE = (
    "O PDF não contém texto extraível (documentos digitalizados não são suportados)."
)
INGESTION_FAILED_MESSAGE = "Falha ao gerar os embeddings do documento."
DOCUMENT_NOT_FOUND_MESSAGE = "Documento {document_id} não encontrado."


@dataclass(frozen=True, slots=True)
class IngestionResult:
    document_id: uuid.UUID
    filename: str
    status: DocumentStatus
    chunk_count: int
    embedded_chunks: int


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class IngestionService:
    """Idempotent: a document is identified by its SHA-256, and only chunks without a vector
    for the active embedding model are embedded, so re-runs resume interrupted ingestions."""

    def __init__(self, session_factory: SessionFactory, embedder: EmbeddingProvider) -> None:
        self._session_factory = session_factory
        self._embedder = embedder

    async def ingest(self, filename: str, data: bytes) -> IngestionResult:
        document_id = await self.store(filename, data)
        return await self.embed_pending(document_id)

    async def store(self, filename: str, data: bytes) -> uuid.UUID:
        digest = content_hash(data)
        async with self._session_factory() as session:
            repository = DocumentRepository(session)
            existing = await repository.get_by_hash(digest)
            if existing is not None:
                return existing.id
            pages = await asyncio.to_thread(extract_pages, data)
            drafts = chunk_pages(pages)
            if not drafts:
                raise InvalidDocumentError(EMPTY_DOCUMENT_MESSAGE)
            document = repository.add(filename, digest, len(pages), drafts)
            await session.commit()
            return document.id

    async def embed_pending(self, document_id: uuid.UUID) -> IngestionResult:
        async with self._session_factory() as session:
            repository = DocumentRepository(session)
            document = await repository.get(document_id)
            if document is None:
                raise LookupError(DOCUMENT_NOT_FOUND_MESSAGE.format(document_id=document_id))
            pending = await repository.chunks_missing_embeddings(
                document_id, self._embedder.embedding_model
            )
            if pending:
                await self._embed_chunks(session, repository, document, pending)
            document.status = DocumentStatus.READY
            document.error = None
            await session.commit()
            chunk_count = len(await document.awaitable_attrs.chunks)
            return IngestionResult(
                document.id, document.filename, document.status, chunk_count, len(pending)
            )

    async def _embed_chunks(
        self,
        session: AsyncSession,
        repository: DocumentRepository,
        document: Document,
        pending: Sequence[Chunk],
    ) -> None:
        try:
            vectors = await self._embedder.embed([chunk.content for chunk in pending])
        except Exception:
            await self._mark_failed(session, document)
            raise
        repository.add_embeddings(
            self._embedder.embedding_model,
            zip((chunk.id for chunk in pending), vectors, strict=True),
        )

    @staticmethod
    async def _mark_failed(session: AsyncSession, document: Document) -> None:
        await session.rollback()
        document.status = DocumentStatus.FAILED
        document.error = INGESTION_FAILED_MESSAGE
        await session.commit()
        logger.warning("ingestion_failed", document_id=str(document.id))
