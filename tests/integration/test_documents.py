import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import func, select, update

from chatbot_api.api.routes import documents
from chatbot_api.db.models import Chunk, ChunkEmbedding, UploadSession
from chatbot_api.db.repository import DocumentRepository
from chatbot_api.db.session import SessionFactory
from chatbot_api.ingestion.pipeline import IngestionService
from chatbot_api.uploads import service
from chatbot_api.uploads.service import safe_filename
from tests.conftest import ACCESS_TOKEN, ADMIN_TOKEN, auth_header
from tests.fakes import FakeEmbeddingProvider, build_pdf

TEST_PART_SIZE = 256
ADMIN = auth_header(ADMIN_TOKEN)
PAGE = "Acolhimento e escuta qualificada em saúde mental na atenção primária. " * 12
PDF = build_pdf([PAGE, PAGE.replace("Acolhimento", "Vínculo")])


@pytest.fixture(autouse=True)
def small_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "PART_SIZE_BYTES", TEST_PART_SIZE)
    monkeypatch.setattr(documents, "PART_SIZE_BYTES", TEST_PART_SIZE)


@pytest.fixture
def embedder(app: FastAPI) -> FakeEmbeddingProvider:
    provider = FakeEmbeddingProvider()
    app.state.provider = provider
    return provider


@pytest.fixture
async def api(
    client: AsyncClient, embedder: FakeEmbeddingProvider, session_factory: SessionFactory
) -> AsyncIterator[AsyncClient]:
    yield client


def parts_of(data: bytes) -> list[bytes]:
    return [data[start : start + TEST_PART_SIZE] for start in range(0, len(data), TEST_PART_SIZE)]


async def create_upload(api: AsyncClient, data: bytes, **overrides: Any) -> dict[str, Any]:
    payload = {
        "filename": "apostila.pdf",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        **overrides,
    }
    response = await api.post("/v1/documents/uploads", json=payload, headers=ADMIN)
    assert response.status_code == HTTPStatus.CREATED, response.text
    body: dict[str, Any] = response.json()
    return body


async def put_part(api: AsyncClient, upload_id: str, number: int, data: bytes) -> Response:
    return await api.put(
        f"/v1/documents/uploads/{upload_id}/parts/{number}", content=data, headers=ADMIN
    )


async def complete(api: AsyncClient, upload_id: str) -> Response:
    return await api.post(f"/v1/documents/uploads/{upload_id}/complete", headers=ADMIN)


async def upload_all(api: AsyncClient, data: bytes) -> Response:
    upload = await create_upload(api, data)
    for number, part in reversed(list(enumerate(parts_of(data), start=1))):
        assert (await put_part(api, upload["id"], number, part)).status_code == HTTPStatus.OK
    return await complete(api, upload["id"])


async def test_full_multipart_upload_ingests_document(api: AsyncClient) -> None:
    response = await upload_all(api, PDF)

    assert response.status_code == HTTPStatus.ACCEPTED
    created = response.json()
    assert created["filename"] == "apostila.pdf"
    assert created["page_count"] == 2
    assert created["chunk_count"] > 0

    document = (await api.get(f"/v1/documents/{created['id']}", headers=ADMIN)).json()
    assert document["status"] == "ready"
    listing = (await api.get("/v1/documents", headers=ADMIN)).json()
    assert [item["id"] for item in listing["data"]] == [created["id"]]


async def test_upload_progress_allows_resuming(api: AsyncClient) -> None:
    upload = await create_upload(api, PDF)
    first_part = parts_of(PDF)[0]
    await put_part(api, upload["id"], 1, first_part)
    await put_part(api, upload["id"], 1, first_part)

    state = (await api.get(f"/v1/documents/uploads/{upload['id']}", headers=ADMIN)).json()

    assert state["received_parts"] == [1]
    assert state["total_parts"] == len(parts_of(PDF))
    assert state["part_size"] == TEST_PART_SIZE
    assert state["status"] == "open"


async def test_complete_requires_all_parts(api: AsyncClient) -> None:
    upload = await create_upload(api, PDF)
    await put_part(api, upload["id"], 1, parts_of(PDF)[0])

    response = await complete(api, upload["id"])

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["error"]["code"] == "upload_incomplete"


async def test_rejects_checksum_mismatch(api: AsyncClient) -> None:
    upload = await create_upload(api, PDF, sha256="0" * 64)
    for number, part in enumerate(parts_of(PDF), start=1):
        await put_part(api, upload["id"], number, part)

    response = await complete(api, upload["id"])

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["error"]["code"] == "checksum_mismatch"


async def test_rejects_files_that_are_not_pdf(api: AsyncClient) -> None:
    response = await upload_all(api, b"MZ" + b"x" * 300)

    assert response.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    assert response.json()["error"]["code"] == "unsupported_file_type"


async def test_rejects_pdf_without_text(api: AsyncClient) -> None:
    response = await upload_all(api, build_pdf(["", ""]))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["error"]["code"] == "invalid_document"


@pytest.mark.parametrize(
    ("number", "data", "status", "code"),
    [
        (99, b"x", HTTPStatus.BAD_REQUEST, "invalid_part_number"),
        (1, b"short", HTTPStatus.BAD_REQUEST, "invalid_part_size"),
        (1, b"x" * (TEST_PART_SIZE + 1), HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "part_too_large"),
    ],
)
async def test_validates_parts(
    api: AsyncClient, number: int, data: bytes, status: HTTPStatus, code: str
) -> None:
    upload = await create_upload(api, PDF)

    response = await put_part(api, upload["id"], number, data)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


async def test_completed_upload_cannot_be_reused(api: AsyncClient) -> None:
    upload = await create_upload(api, PDF)
    for number, part in enumerate(parts_of(PDF), start=1):
        await put_part(api, upload["id"], number, part)
    await complete(api, upload["id"])

    response = await complete(api, upload["id"])

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["error"]["code"] == "upload_not_open"
    state = (await api.get(f"/v1/documents/uploads/{upload['id']}", headers=ADMIN)).json()
    assert state["status"] == "completed"
    assert state["document_id"] is not None


async def test_expired_upload_is_rejected_and_cleaned(
    api: AsyncClient, session_factory: SessionFactory
) -> None:
    upload = await create_upload(api, PDF)
    async with session_factory() as session:
        await session.execute(
            update(UploadSession).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()

    expired = await put_part(api, upload["id"], 1, parts_of(PDF)[0])
    await create_upload(api, PDF)
    cleaned = await api.get(f"/v1/documents/uploads/{upload['id']}", headers=ADMIN)

    assert expired.status_code == HTTPStatus.GONE
    assert cleaned.status_code == HTTPStatus.NOT_FOUND
    assert cleaned.json()["error"]["code"] == "upload_not_found"


async def test_duplicate_file_returns_existing_document(api: AsyncClient) -> None:
    first = (await upload_all(api, PDF)).json()

    second = (await upload_all(api, PDF)).json()

    assert second["id"] == first["id"]


async def test_background_failure_marks_document_failed(
    api: AsyncClient, embedder: FakeEmbeddingProvider
) -> None:
    embedder.fail = True

    created = (await upload_all(api, PDF)).json()

    document = (await api.get(f"/v1/documents/{created['id']}", headers=ADMIN)).json()
    assert document["status"] == "failed"
    assert document["error"] == "Falha ao gerar os embeddings do documento."


async def test_create_validations(api: AsyncClient) -> None:
    too_large = await api.post(
        "/v1/documents/uploads",
        json={"filename": "a.pdf", "size": 10**12, "sha256": "a" * 64},
        headers=ADMIN,
    )
    bad_name = await api.post(
        "/v1/documents/uploads",
        json={"filename": "../", "size": 10, "sha256": "a" * 64},
        headers=ADMIN,
    )
    bad_hash = await api.post(
        "/v1/documents/uploads",
        json={"filename": "a.pdf", "size": 10, "sha256": "XYZ"},
        headers=ADMIN,
    )

    assert too_large.json()["error"]["code"] == "file_too_large"
    assert bad_name.json()["error"]["code"] == "invalid_filename"
    assert bad_hash.status_code == HTTPStatus.BAD_REQUEST


async def direct_upload(api: AsyncClient, data: bytes, filename: str = "direta.pdf") -> Response:
    return await api.post(
        "/v1/documents", params={"filename": filename}, content=data, headers=ADMIN
    )


async def count_rows(session_factory: SessionFactory, model: type[Chunk | ChunkEmbedding]) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model)) or 0


async def test_direct_upload_ingests_document(api: AsyncClient) -> None:
    response = await direct_upload(api, PDF, "../pasta/direta.pdf")

    assert response.status_code == HTTPStatus.ACCEPTED
    created = response.json()
    assert created["filename"] == "direta.pdf"
    assert created["page_count"] == 2
    document = (await api.get(f"/v1/documents/{created['id']}", headers=ADMIN)).json()
    assert document["status"] == "ready"


async def test_direct_upload_deduplicates_with_multipart_upload(api: AsyncClient) -> None:
    first = (await upload_all(api, PDF)).json()

    second = (await direct_upload(api, PDF)).json()

    assert second["id"] == first["id"]


async def test_direct_upload_validations(api: AsyncClient, app: FastAPI) -> None:
    not_pdf = await direct_upload(api, b"MZ" + b"x" * 300)
    bad_name = await direct_upload(api, PDF, "..")
    no_text = await direct_upload(api, build_pdf(["", ""]))
    app.state.settings = app.state.settings.model_copy(
        update={"direct_upload_max_bytes": len(PDF) - 1}
    )
    too_large = await direct_upload(api, PDF)

    assert not_pdf.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    assert bad_name.json()["error"]["code"] == "invalid_filename"
    assert no_text.json()["error"]["code"] == "invalid_document"
    assert too_large.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    assert too_large.json()["error"]["code"] == "file_too_large"


async def test_delete_document_removes_chunks_and_embeddings(
    api: AsyncClient, session_factory: SessionFactory
) -> None:
    created = (await direct_upload(api, PDF)).json()
    assert await count_rows(session_factory, ChunkEmbedding) > 0

    response = await api.delete(f"/v1/documents/{created['id']}", headers=ADMIN)

    assert response.status_code == HTTPStatus.NO_CONTENT
    assert response.content == b""
    missing = await api.get(f"/v1/documents/{created['id']}", headers=ADMIN)
    assert missing.status_code == HTTPStatus.NOT_FOUND
    assert await count_rows(session_factory, Chunk) == 0
    assert await count_rows(session_factory, ChunkEmbedding) == 0


async def test_background_embedding_of_deleted_document_is_skipped(
    session_factory: SessionFactory, embedder: FakeEmbeddingProvider
) -> None:
    ingestion = IngestionService(session_factory, embedder)
    document_id = await ingestion.store("apagado.pdf", PDF)
    async with session_factory() as session:
        await DocumentRepository(session).delete(document_id)
        await session.commit()

    await documents.embed_in_background(ingestion, document_id)

    assert await count_rows(session_factory, ChunkEmbedding) == 0


async def test_delete_unknown_document_returns_not_found(api: AsyncClient) -> None:
    response = await api.delete("/v1/documents/00000000-0000-0000-0000-000000000000", headers=ADMIN)

    assert response.status_code == HTTPStatus.NOT_FOUND


async def test_reset_requires_confirmation_and_clears_everything(
    api: AsyncClient, session_factory: SessionFactory
) -> None:
    await upload_all(api, PDF)
    await direct_upload(api, build_pdf([PAGE.replace("Acolhimento", "Matriciamento")]))
    await create_upload(api, PDF)

    unconfirmed = await api.delete("/v1/documents", headers=ADMIN)
    response = await api.delete("/v1/documents", params={"confirm": "true"}, headers=ADMIN)

    assert unconfirmed.status_code == HTTPStatus.BAD_REQUEST
    assert unconfirmed.json()["error"]["code"] == "confirmation_required"
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"deleted_documents": 2, "deleted_uploads": 2}
    assert (await api.get("/v1/documents", headers=ADMIN)).json() == {"data": []}
    assert await count_rows(session_factory, Chunk) == 0


async def test_reset_can_be_disabled(api: AsyncClient, app: FastAPI) -> None:
    app.state.settings = app.state.settings.model_copy(update={"documents_reset_enabled": False})

    response = await api.delete("/v1/documents", params={"confirm": "true"}, headers=ADMIN)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["error"]["code"] == "reset_disabled"


async def test_delete_routes_require_admin_token(api: AsyncClient) -> None:
    response = await api.delete("/v1/documents", headers=auth_header(ACCESS_TOKEN))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


async def test_unknown_document_returns_not_found(api: AsyncClient) -> None:
    response = await api.get("/v1/documents/00000000-0000-0000-0000-000000000000", headers=ADMIN)

    assert response.status_code == HTTPStatus.NOT_FOUND


async def test_documents_require_admin_token(api: AsyncClient) -> None:
    response = await api.get("/v1/documents", headers=auth_header(ACCESS_TOKEN))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\x\\apostila.pdf", "apostila.pdf"),
        ("..", None),
        ("  ", None),
    ],
)
def test_safe_filename_strips_paths(raw: str, expected: str | None) -> None:
    assert safe_filename(raw) == expected
