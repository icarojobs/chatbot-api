from pathlib import Path

import pytest

from chatbot_api import ingest
from chatbot_api.core.config import Settings
from tests.fakes import FakeEmbeddingProvider, build_pdf

PAGE = "Cuidado em saúde mental na atenção primária. " * 5


@pytest.fixture(autouse=True)
def fake_provider(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(ingest, "get_settings", lambda: settings)
    monkeypatch.setattr(
        ingest, "OpenAICompatibleProvider", lambda _client, model: FakeEmbeddingProvider(model)
    )


def test_ingests_directory_of_pdfs(
    tmp_path: Path, session_factory: object, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.pdf").write_bytes(build_pdf([PAGE]))
    (tmp_path / "b.pdf").write_bytes(build_pdf([PAGE + " Outra."]))
    (tmp_path / "ignorado.txt").write_text("x")

    assert ingest.main([str(tmp_path)]) == ingest.EXIT_OK

    output = capsys.readouterr().out
    assert "[ready] a.pdf: 1 trechos (1 novos embeddings)" in output
    assert "[ready] b.pdf" in output


def test_reports_invalid_and_missing_files(
    tmp_path: Path, session_factory: object, capsys: pytest.CaptureFixture[str]
) -> None:
    invalid = tmp_path / "falso.pdf"
    invalid.write_bytes(b"not a pdf")

    exit_code = ingest.main([str(invalid), str(tmp_path / "inexistente.pdf")])

    assert exit_code == ingest.EXIT_FAILURE
    output = capsys.readouterr().out
    assert "[erro] falso.pdf: O arquivo não é um PDF válido." in output
    assert "[erro] inexistente.pdf" in output
