import uuid
from collections.abc import Iterable, Sequence
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from chatbot_api.db.models import Chunk, ChunkEmbedding, Document, DocumentStatus
from chatbot_api.ingestion.chunking import ChunkDraft


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_hash(self, content_hash: str) -> Document | None:
        return await self._session.scalar(
            select(Document).where(Document.content_hash == content_hash)
        )

    async def get(self, document_id: uuid.UUID) -> Document | None:
        return await self._session.get(Document, document_id)

    async def list_with_chunk_counts(
        self, document_id: uuid.UUID | None = None
    ) -> list[tuple[Document, int]]:
        statement = (
            select(Document, func.count(Chunk.id))
            .outerjoin(Chunk, Chunk.document_id == Document.id)
            .group_by(Document.id)
            .order_by(Document.created_at)
        )
        if document_id is not None:
            statement = statement.where(Document.id == document_id)
        rows = await self._session.execute(statement)
        return [(document, count) for document, count in rows]

    async def delete(self, document_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            delete(Document).where(Document.id == document_id).returning(Document.id)
        )
        return result.first() is not None

    async def delete_all(self) -> int:
        result = cast(CursorResult[Any], await self._session.execute(delete(Document)))
        return result.rowcount

    def add(
        self, filename: str, content_hash: str, page_count: int, drafts: Sequence[ChunkDraft]
    ) -> Document:
        document = Document(
            filename=filename,
            content_hash=content_hash,
            page_count=page_count,
            status=DocumentStatus.PROCESSING,
            chunks=[
                Chunk(
                    chunk_index=draft.chunk_index,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    content=draft.content,
                )
                for draft in drafts
            ],
        )
        self._session.add(document)
        return document

    async def chunks_missing_embeddings(
        self, document_id: uuid.UUID, embedding_model: str
    ) -> Sequence[Chunk]:
        embedded = select(ChunkEmbedding.chunk_id).where(
            ChunkEmbedding.embedding_model == embedding_model
        )
        result = await self._session.scalars(
            select(Chunk)
            .where(Chunk.document_id == document_id, Chunk.id.not_in(embedded))
            .order_by(Chunk.chunk_index)
        )
        return result.all()

    def add_embeddings(
        self, embedding_model: str, pairs: Iterable[tuple[uuid.UUID, list[float]]]
    ) -> None:
        self._session.add_all(
            ChunkEmbedding(chunk_id=chunk_id, embedding_model=embedding_model, embedding=vector)
            for chunk_id, vector in pairs
        )
