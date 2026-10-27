import re
import unicodedata

# Some PDFs lose the "fi"/"fl" ligature glyphs and pypdf emits NUL in their place.
# Measured on the knowledge base: "fl" precedes e/u ("reflexão", "influência", "fluxo"),
# "it"/"ag"/"or" ("conflito", "flagrante", "flor"); every other occurrence is "fi".
DUPLICATED_LIGATURE = re.compile(r"\x00(?=f[il])")
FL_LIGATURE = re.compile(r"\x00(?=[eéêuú]|it|ag|or)")
# One PDF drops the glyph entirely, leaving a space: "pro ssionais".
DROPPED_FI_LIGATURE = re.compile(r"\b(pro|multipro|interpro)\s(ssion)", re.IGNORECASE)
LOST_LIGATURE = "\x00"
FI = "fi"
FL = "fl"

HYPHENATED_LINE_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")
CONTROL_CHARACTERS = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f­]")
WHITESPACE = re.compile(r"\s+")


def restore_ligatures(text: str) -> str:
    text = DUPLICATED_LIGATURE.sub("", text)
    text = FL_LIGATURE.sub(FL, text)
    text = DROPPED_FI_LIGATURE.sub(rf"\1{FI}\2", text)
    return text.replace(LOST_LIGATURE, FI)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", restore_ligatures(text))
    text = HYPHENATED_LINE_BREAK.sub(r"\1\2", text)
    text = CONTROL_CHARACTERS.sub("", text)
    return WHITESPACE.sub(" ", text).strip()
