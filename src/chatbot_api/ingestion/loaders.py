import io
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from chatbot_api.ingestion.normalization import normalize_text

PDF_MAGIC_BYTES = b"%PDF-"
INVALID_PDF_MESSAGE = "O arquivo não é um PDF válido."


class InvalidDocumentError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PageText:
    page_number: int
    text: str


def is_pdf(data: bytes) -> bool:
    return data.startswith(PDF_MAGIC_BYTES)


def extract_pages(data: bytes) -> list[PageText]:
    """CPU-bound: call it through asyncio.to_thread."""
    if not is_pdf(data):
        raise InvalidDocumentError(INVALID_PDF_MESSAGE)
    try:
        reader = PdfReader(io.BytesIO(data))
        raw_pages = [page.extract_text() or "" for page in reader.pages]
    except (PyPdfError, ValueError, KeyError) as exc:
        raise InvalidDocumentError(INVALID_PDF_MESSAGE) from exc
    return [
        PageText(page_number=number, text=normalize_text(raw))
        for number, raw in enumerate(raw_pages, start=1)
    ]
