import pytest

from chatbot_api.ingestion.normalization import normalize_text, restore_ligatures


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pro\x00ssionais", "profissionais"),
        ("di\x00culdade", "dificuldade"),
        ("\x00lhos", "filhos"),
        ("re\x00exão", "reflexão"),
        ("re\x00etir", "refletir"),
        ("in\x00uência", "influência"),
        ("con\x00itos", "conflitos"),
        ("\x00uxo", "fluxo"),
        ("pro\x00fissionais", "profissionais"),
        ("con\x00flito", "conflito"),
        ("escassez de pro ssionais", "escassez de profissionais"),
        ("equipe multipro ssional", "equipe multiprofissional"),
    ],
)
def test_restores_lost_ligatures(raw: str, expected: str) -> None:
    assert restore_ligatures(raw) == expected


def test_joins_hyphenated_line_breaks_and_collapses_whitespace() -> None:
    raw = "aten-\n ção  primária\n\nà\xa0saúde\x0c mental­ "

    assert normalize_text(raw) == "atenção primária à saúde mental"


def test_normalizes_unicode_composition() -> None:
    assert normalize_text("saúde") == "saúde"
