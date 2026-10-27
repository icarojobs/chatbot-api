from collections.abc import Sequence

FAKE_EMBEDDING_MODEL = "fake-embedding"
FAKE_DIMENSION = 8
PDF_HEADER = b"%PDF-1.4\n"


class FakeEmbeddingProvider:
    def __init__(self, model: str = FAKE_EMBEDDING_MODEL, fail: bool = False) -> None:
        self._model = model
        self.fail = fail
        self.calls: list[int] = []

    @property
    def embedding_model(self) -> str:
        return self._model

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self.fail:
            raise RuntimeError("embedding provider down")
        self.calls.append(len(texts))
        return [self.vector_for(text) for text in texts]

    @staticmethod
    def vector_for(text: str) -> list[float]:
        return [float((len(text) + index) % 7) + 1.0 for index in range(FAKE_DIMENSION)]

    async def close(self) -> None:
        return None


def _escape(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return escaped.encode("cp1252")


def build_pdf(pages: Sequence[str]) -> bytes:
    """Minimal valid PDF with one text line per page (Helvetica, WinAnsi)."""
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    }
    kids: list[str] = []
    for position, text in enumerate(pages):
        page_id, content_id = 4 + position * 2, 5 + position * 2
        stream = b"BT /F1 12 Tf 72 720 Td (" + _escape(text) + b") Tj ET"
        objects[content_id] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        objects[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content_id
        )
        kids.append(f"{page_id} 0 R")
    objects[2] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode()

    output = bytearray(PDF_HEADER)
    offsets: dict[int, int] = {}
    for object_id in sorted(objects):
        offsets[object_id] = len(output)
        output += b"%d 0 obj\n" % object_id + objects[object_id] + b"\nendobj\n"
    xref_offset = len(output)
    size = max(objects) + 1
    output += b"xref\n0 %d\n0000000000 65535 f \n" % size
    output += b"".join(b"%010d 00000 n \n" % offsets[object_id] for object_id in range(1, size))
    output += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        size,
        xref_offset,
    )
    return bytes(output)
