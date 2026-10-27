import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select

from chatbot_api.db.models import Chunk, ChunkEmbedding, Document, DocumentStatus
from chatbot_api.db.session import SessionFactory


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_start: int
    page_end: int
    content: str
    score: float


class Retriever(Protocol):
    async def search(
        self, query_vector: Sequence[float], embedding_model: str, top_k: int
    ) -> list[RetrievedChunk]: ...


class ChunkRetriever:
    """Exact cosine KNN over the active embedding model (see ADR-0003: no HNSW at this scale)."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def search(
        self, query_vector: Sequence[float], embedding_model: str, top_k: int
    ) -> list[RetrievedChunk]:
        distance = ChunkEmbedding.embedding.cosine_distance(query_vector)
        statement = (
            select(Chunk, Document.filename, (1 - distance).label("score"))
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
            .join(Document, Document.id == Chunk.document_id)
            .where(
                ChunkEmbedding.embedding_model == embedding_model,
                Document.status == DocumentStatus.READY,
            )
            .order_by(distance)
            .limit(top_k)
        )
        async with self._session_factory() as session:
            rows = await session.execute(statement)
            return [
                RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    filename=filename,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    content=chunk.content,
                    score=float(score),
                )
                for chunk, filename, score in rows
            ]
