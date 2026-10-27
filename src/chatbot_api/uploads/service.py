import hashlib
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import PurePath

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from chatbot_api.core.errors import ApiError, ErrorType
from chatbot_api.db.models import UploadPart, UploadSession, UploadStatus
from chatbot_api.db.session import SessionFactory
from chatbot_api.ingestion.loaders import INVALID_PDF_MESSAGE, InvalidDocumentError, is_pdf
from chatbot_api.ingestion.pipeline import IngestionService

# Below Vercel's 4.5 MB request limit, so the same client works on any host.
PART_SIZE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class UploadState:
    upload: UploadSession
    received_parts: list[int]

    @property
    def total_parts(self) -> int:
        return total_parts(self.upload.total_size, self.upload.part_size)


def total_parts(total_size: int, part_size: int) -> int:
    return math.ceil(total_size / part_size)


def expected_part_size(upload: UploadSession, part_number: int) -> int:
    last_part = total_parts(upload.total_size, upload.part_size)
    if part_number < last_part:
        return upload.part_size
    return upload.total_size - upload.part_size * (last_part - 1)


RESERVED_NAMES = frozenset({"", ".", ".."})


def safe_filename(filename: str) -> str | None:
    name = PurePath(filename.replace("\\", "/")).name.strip()
    return None if name in RESERVED_NAMES else name


def _error(status: HTTPStatus, message: str, code: str) -> ApiError:
    return ApiError(status, message, ErrorType.INVALID_REQUEST, code)


UPLOAD_NOT_FOUND = (HTTPStatus.NOT_FOUND, "Upload não encontrado.", "upload_not_found")
UPLOAD_EXPIRED = (HTTPStatus.GONE, "O upload expirou. Inicie um novo.", "upload_expired")
UPLOAD_NOT_OPEN = (HTTPStatus.CONFLICT, "O upload já foi concluído.", "upload_not_open")
FILE_TOO_LARGE = (
    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    "O arquivo excede o tamanho máximo de {limit} bytes.",
    "file_too_large",
)
INVALID_FILENAME = (HTTPStatus.BAD_REQUEST, "Nome de arquivo inválido.", "invalid_filename")
INVALID_PART_NUMBER = (
    HTTPStatus.BAD_REQUEST,
    "Número de parte inválido: use de 1 a {total}.",
    "invalid_part_number",
)
INVALID_PART_SIZE = (
    HTTPStatus.BAD_REQUEST,
    "A parte {part} deve ter exatamente {expected} bytes (recebidos {received}).",
    "invalid_part_size",
)
MISSING_PARTS = (HTTPStatus.CONFLICT, "Partes pendentes: {missing}.", "upload_incomplete")
CHECKSUM_MISMATCH = (
    HTTPStatus.UNPROCESSABLE_ENTITY,
    "O SHA-256 do arquivo montado não confere com o informado.",
    "checksum_mismatch",
)
NOT_A_PDF = (HTTPStatus.UNSUPPORTED_MEDIA_TYPE, INVALID_PDF_MESSAGE, "unsupported_file_type")
INVALID_DOCUMENT_CODE = "invalid_document"


class UploadService:
    def __init__(self, session_factory: SessionFactory, max_bytes: int, ttl: timedelta) -> None:
        self._session_factory = session_factory
        self._max_bytes = max_bytes
        self._ttl = ttl

    async def create(self, filename: str, size: int, sha256: str) -> UploadState:
        name = safe_filename(filename)
        if name is None:
            raise _error(*INVALID_FILENAME)
        if size > self._max_bytes:
            status, message, code = FILE_TOO_LARGE
            raise _error(status, message.format(limit=self._max_bytes), code)
        async with self._session_factory() as session:
            await session.execute(
                delete(UploadSession).where(UploadSession.expires_at < func.now())
            )
            upload = UploadSession(
                filename=name,
                total_size=size,
                part_size=PART_SIZE_BYTES,
                sha256=sha256,
                status=UploadStatus.OPEN,
                expires_at=datetime.now(UTC) + self._ttl,
            )
            session.add(upload)
            await session.commit()
            return UploadState(upload, [])

    async def state(self, upload_id: uuid.UUID) -> UploadState:
        async with self._session_factory() as session:
            upload = await self._get(session, upload_id)
            return UploadState(upload, await self._received_parts(session, upload_id))

    async def put_part(self, upload_id: uuid.UUID, part_number: int, data: bytes) -> UploadState:
        async with self._session_factory() as session:
            upload = await self._get_open(session, upload_id)
            self._validate_part(upload, part_number, len(data))
            await session.execute(
                insert(UploadPart)
                .values(upload_id=upload_id, part_number=part_number, data=data)
                .on_conflict_do_update(
                    index_elements=[UploadPart.upload_id, UploadPart.part_number],
                    set_={"data": data},
                )
            )
            await session.commit()
            return UploadState(upload, await self._received_parts(session, upload_id))

    async def complete(self, upload_id: uuid.UUID, ingestion: IngestionService) -> uuid.UUID:
        async with self._session_factory() as session:
            upload = await self._get_open(session, upload_id)
            data = await self._assemble(session, upload)
            try:
                document_id = await ingestion.store(upload.filename, data)
            except InvalidDocumentError as exc:
                raise _error(
                    HTTPStatus.UNPROCESSABLE_ENTITY, str(exc), INVALID_DOCUMENT_CODE
                ) from exc
            upload.status = UploadStatus.COMPLETED
            upload.document_id = document_id
            await session.execute(delete(UploadPart).where(UploadPart.upload_id == upload_id))
            await session.commit()
            return document_id

    async def _assemble(self, session: AsyncSession, upload: UploadSession) -> bytes:
        received = await self._received_parts(session, upload.id)
        expected = range(1, total_parts(upload.total_size, upload.part_size) + 1)
        missing = sorted(set(expected) - set(received))
        if missing:
            status, message, code = MISSING_PARTS
            raise _error(status, message.format(missing=missing), code)
        parts = await session.scalars(
            select(UploadPart.data)
            .where(UploadPart.upload_id == upload.id)
            .order_by(UploadPart.part_number)
        )
        data = b"".join(parts)
        if hashlib.sha256(data).hexdigest() != upload.sha256:
            raise _error(*CHECKSUM_MISMATCH)
        if not is_pdf(data):
            raise _error(*NOT_A_PDF)
        return data

    @staticmethod
    def _validate_part(upload: UploadSession, part_number: int, received: int) -> None:
        last_part = total_parts(upload.total_size, upload.part_size)
        if not 1 <= part_number <= last_part:
            status, message, code = INVALID_PART_NUMBER
            raise _error(status, message.format(total=last_part), code)
        expected = expected_part_size(upload, part_number)
        if received != expected:
            status, message, code = INVALID_PART_SIZE
            raise _error(
                status, message.format(part=part_number, expected=expected, received=received), code
            )

    @staticmethod
    async def _received_parts(session: AsyncSession, upload_id: uuid.UUID) -> list[int]:
        result = await session.scalars(
            select(UploadPart.part_number)
            .where(UploadPart.upload_id == upload_id)
            .order_by(UploadPart.part_number)
        )
        return list(result.all())

    @staticmethod
    async def _get(session: AsyncSession, upload_id: uuid.UUID) -> UploadSession:
        upload = await session.get(UploadSession, upload_id)
        if upload is None:
            raise _error(*UPLOAD_NOT_FOUND)
        return upload

    async def _get_open(self, session: AsyncSession, upload_id: uuid.UUID) -> UploadSession:
        upload = await self._get(session, upload_id)
        if upload.status is not UploadStatus.OPEN:
            raise _error(*UPLOAD_NOT_OPEN)
        if upload.expires_at < datetime.now(UTC):
            raise _error(*UPLOAD_EXPIRED)
        return upload
