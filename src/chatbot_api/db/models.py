import uuid
from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

FILENAME_MAX_LENGTH = 255
SHA256_HEX_LENGTH = 64
MODEL_NAME_MAX_LENGTH = 128
STATUS_MAX_LENGTH = 20


class Base(AsyncAttrs, DeclarativeBase):
    pass


class DocumentStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(FILENAME_MAX_LENGTH))
    content_hash: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH), unique=True)
    page_count: Mapped[int]
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(
            DocumentStatus,
            native_enum=False,
            length=STATUS_MAX_LENGTH,
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        default=DocumentStatus.PROCESSING,
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int]
    page_start: Mapped[int]
    page_end: Mapped[int]
    content: Mapped[str] = mapped_column(Text)

    document: Mapped[Document] = relationship(back_populates="chunks")


class ChunkEmbedding(Base):
    """Vectors are keyed by model: dev (Ollama) and prod embeddings have different dimensions."""

    __tablename__ = "chunk_embeddings"

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    embedding_model: Mapped[str] = mapped_column(String(MODEL_NAME_MAX_LENGTH), primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector())


class UploadStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(FILENAME_MAX_LENGTH))
    total_size: Mapped[int] = mapped_column(BigInteger)
    part_size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH))
    status: Mapped[UploadStatus] = mapped_column(
        Enum(
            UploadStatus,
            native_enum=False,
            length=STATUS_MAX_LENGTH,
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        default=UploadStatus.OPEN,
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UploadPart(Base):
    __tablename__ = "upload_parts"

    upload_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("upload_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    part_number: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)
