import pytest

from chatbot_api.ingestion.loaders import InvalidDocumentError, extract_pages, is_pdf
from tests.fakes import build_pdf


def test_extracts_normalized_text_per_page() -> None:
    data = build_pdf(["Saúde mental na atenção primária.", "Segunda   página."])

    pages = extract_pages(data)

    assert [page.page_number for page in pages] == [1, 2]
    assert pages[0].text == "Saúde mental na atenção primária."
    assert pages[1].text == "Segunda página."


def test_rejects_non_pdf_bytes() -> None:
    assert is_pdf(b"hello") is False
    with pytest.raises(InvalidDocumentError):
        extract_pages(b"MZ\x90\x00 not a pdf")


def test_rejects_corrupted_pdf() -> None:
    with pytest.raises(InvalidDocumentError):
        extract_pages(b"%PDF-1.4\n garbage without objects")
