"""Deterministic prompt injection screening, applied before any model call.

Catches the classic, high-signal phrasings (instruction override, prompt extraction, persona
swaps, encoded payloads) and any attempt to open or close the prompt's own blocks, which no
legitimate question contains. It is one layer of defense in depth: phrasings it misses still meet
the hardened prompt and the delimited, neutralized blocks in `prompting.py` (ADR-0008).
"""

import re
import unicodedata
from collections.abc import Iterable

from chatbot_api.rag.prompting import RESERVED_TAGS

_INSTRUCTIONS = r"(instrucoes|regras|diretrizes|prompt|instructions|rules|guidelines)"

INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(pattern, re.IGNORECASE)
    for name, pattern in {
        "instruction_override": (
            r"\b(ignore|ignorem|desconsidere|desconsiderem|esqueca|esquecam|disregard|forget|"
            r"override)\b.{0,40}\b" + _INSTRUCTIONS
        ),
        "prompt_extraction": (
            r"\b(revele|mostre|copie|repita|imprima|exiba|liste|reveal|show|print|repeat|"
            r"output)\b.{0,60}\b(" + _INSTRUCTIONS + r".{0,25}\b(recebeu|recebidas|anteriores|"
            r"do sistema|you received|above|previous)\b|system prompt|prompt do sistema|"
            r"prompt de sistema|suas (instrucoes|regras)|your (instructions|rules))"
        ),
        "persona_swap": (
            r"\b(a partir de agora|de agora em diante|from now on)\b.{0,30}\b(voce|you)\b|"
            r"\bvoce agora e\b|\byou are now\b|\b(dan|jailbreak|modo desenvolvedor|"
            r"developer mode)\b"
        ),
        "encoded_payload": (
            r"\b(decodifique|decode|base64)\b.{0,80}\b(execute|siga|obedeca|follow|run|obey)\b"
        ),
    }.items()
} | {"delimiter_injection": RESERVED_TAGS}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def detect_injection(texts: Iterable[str]) -> list[str]:
    folded = [_fold(text) for text in texts if text]
    return [
        name
        for name, pattern in INJECTION_PATTERNS.items()
        if any(pattern.search(text) for text in folded)
    ]
