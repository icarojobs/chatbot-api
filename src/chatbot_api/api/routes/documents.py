import uuid
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Path, Request
from pydantic import BaseModel, Field

from chatbot_api.core.config import Settings
from chatbot_api.core.errors import ApiError, ErrorType
from chatbot_api.core.security import require_admin_token
from chatbot_api.db.models import Document, DocumentStatus, UploadStatus
from chatbot_api.db.repository import DocumentRepository
from chatbot_api.db.session import SessionFactory
from chatbot_api.ingestion.pipeline import IngestionService
from chatbot_api.uploads.service import PART_SIZE_BYTES, UploadService, UploadState

logger = structlog.get_logger(__name__)

SHA256_PATTERN = r"^[0-9a-f]{64}$"
FILENAME_MAX_LENGTH = 255
DOCUMENT_NOT_FOUND = "Documento não encontrado."
PART_TOO_LARGE = "A parte excede {limit} bytes."

router = APIRouter(
    prefix="/v1/documents", tags=["Documentos"], dependencies=[Depends(require_admin_token)]
)


class CreateUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=FILENAME_MAX_LENGTH, examples=["apostila.pdf"])
    size: int = Field(gt=0, description="Tamanho total do arquivo em bytes.")
    sha256: str = Field(pattern=SHA256_PATTERN, description="SHA-256 (hex minúsculo) do arquivo.")


class UploadResponse(BaseModel):
    id: uuid.UUID
    filename: str
    size: int
    part_size: int
    total_parts: int
    received_parts: list[int]
    status: UploadStatus
    document_id: uuid.UUID | None
    expires_at: datetime


class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: DocumentStatus
    page_count: int
    chunk_count: int
    error: str | None
    created_at: datetime


class DocumentListResponse(BaseModel):
    data: list[DocumentResponse]


def _upload_response(state: UploadState) -> UploadResponse:
    upload = state.upload
    return UploadResponse(
        id=upload.id,
        filename=upload.filename,
        size=upload.total_size,
        part_size=upload.part_size,
        total_parts=state.total_parts,
        received_parts=state.received_parts,
        status=upload.status,
        document_id=upload.document_id,
        expires_at=upload.expires_at,
    )


def _document_response(document: Document, chunk_count: int) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        page_count=document.page_count,
        chunk_count=chunk_count,
        error=document.error,
        created_at=document.created_at,
    )


def get_session_factory(request: Request) -> SessionFactory:
    session_factory: SessionFactory = request.app.state.session_factory
    return session_factory


def get_upload_service(request: Request) -> UploadService:
    settings: Settings = request.app.state.settings
    return UploadService(
        get_session_factory(request),
        settings.upload_max_bytes,
        timedelta(minutes=settings.upload_ttl_minutes),
    )


def get_ingestion_service(request: Request) -> IngestionService:
    return IngestionService(get_session_factory(request), request.app.state.provider)


Sessions = Annotated[SessionFactory, Depends(get_session_factory)]
Uploads = Annotated[UploadService, Depends(get_upload_service)]
Ingestion = Annotated[IngestionService, Depends(get_ingestion_service)]
PartNumber = Annotated[int, Path(ge=1)]


async def read_limited_body(request: Request, limit: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise ApiError(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                PART_TOO_LARGE.format(limit=limit),
                ErrorType.INVALID_REQUEST,
                "part_too_large",
            )
    return bytes(body)


async def embed_in_background(ingestion: IngestionService, document_id: uuid.UUID) -> None:
    try:
        await ingestion.embed_pending(document_id)
    except Exception:
        logger.exception("background_embedding_failed", document_id=str(document_id))


@router.post("/uploads", status_code=HTTPStatus.CREATED, summary="Inicia um upload em partes")
async def create_upload(payload: CreateUploadRequest, uploads: Uploads) -> UploadResponse:
    state = await uploads.create(payload.filename, payload.size, payload.sha256)
    return _upload_response(state)


@router.get("/uploads/{upload_id}", summary="Consulta o progresso de um upload")
async def get_upload(upload_id: uuid.UUID, uploads: Uploads) -> UploadResponse:
    return _upload_response(await uploads.state(upload_id))


@router.put(
    "/uploads/{upload_id}/parts/{part_number}",
    summary="Envia uma parte do arquivo (corpo binário, application/octet-stream)",
)
async def put_upload_part(
    upload_id: uuid.UUID, part_number: PartNumber, request: Request, uploads: Uploads
) -> UploadResponse:
    data = await read_limited_body(request, PART_SIZE_BYTES)
    return _upload_response(await uploads.put_part(upload_id, part_number, data))


@router.post(
    "/uploads/{upload_id}/complete",
    status_code=HTTPStatus.ACCEPTED,
    summary="Conclui o upload: valida, extrai o texto e gera os embeddings em background",
)
async def complete_upload(
    upload_id: uuid.UUID,
    uploads: Uploads,
    ingestion: Ingestion,
    sessions: Sessions,
    background: BackgroundTasks,
) -> DocumentResponse:
    document_id = await uploads.complete(upload_id, ingestion)
    background.add_task(embed_in_background, ingestion, document_id)
    return await _load_document(sessions, document_id)


@router.get("", summary="Lista os documentos da base de conhecimento")
async def list_documents(sessions: Sessions) -> DocumentListResponse:
    async with sessions() as session:
        rows = await DocumentRepository(session).list_with_chunk_counts()
    return DocumentListResponse(data=[_document_response(*row) for row in rows])


@router.get("/{document_id}", summary="Consulta um documento e o status da ingestão")
async def get_document(document_id: uuid.UUID, sessions: Sessions) -> DocumentResponse:
    return await _load_document(sessions, document_id)


async def _load_document(sessions: SessionFactory, document_id: uuid.UUID) -> DocumentResponse:
    async with sessions() as session:
        rows = await DocumentRepository(session).list_with_chunk_counts(document_id)
    if not rows:
        raise ApiError(HTTPStatus.NOT_FOUND, DOCUMENT_NOT_FOUND, ErrorType.NOT_FOUND)
    return _document_response(*rows[0])
