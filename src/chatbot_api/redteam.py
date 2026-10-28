"""Prompt injection red team: uv run python -m chatbot_api.redteam [--model id]

Runs `redteam_cases.ATTACKS` through the real RAG pipeline of the active environment
(API_ENV) and reports which attacks the defenses blocked.
"""

import argparse
import asyncio
import re
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from chatbot_api.core.config import Settings, get_settings
from chatbot_api.core.logging import configure_logging
from chatbot_api.db.session import create_engine, create_session_factory
from chatbot_api.providers.base import ChatModelProvider, EmbeddingProvider
from chatbot_api.providers.openai_compatible import OpenAICompatibleProvider, create_client
from chatbot_api.providers.profile import ProviderProfile, build_provider_profile
from chatbot_api.rag.graph import RAGNodes, RAGSettings, build_rag_graph
from chatbot_api.rag.prompting import SYSTEM_PROMPT
from chatbot_api.rag.retrieval import ChunkRetriever, RetrievedChunk, Retriever
from chatbot_api.rag.service import RAGService, TextDelta
from chatbot_api.redteam_cases import ATTACKS, AttackCase

POISON_FILENAME = "documento-malicioso.pdf"
POISON_SCORE = 1.0
LEAK_FRAGMENT_CHARS = 50
EXCERPT_CHARS = 90
EXIT_FAILURE = 1
UNKNOWN_ATTACK = "Ataque(s) inexistente(s): {names}."


@dataclass(frozen=True, slots=True)
class AttackResult:
    case: AttackCase
    answer: str
    abstained: bool
    violations: tuple[str, ...]

    @property
    def blocked(self) -> bool:
        return not self.violations


class PoisonedRetriever:
    """Prepends a malicious chunk to the real results, simulating an injected PDF."""

    def __init__(self, inner: Retriever, poison: str) -> None:
        self._inner = inner
        self._poison = poison

    async def search(
        self, query_vector: Sequence[float], embedding_model: str, top_k: int
    ) -> list[RetrievedChunk]:
        chunks = await self._inner.search(query_vector, embedding_model, top_k)
        if not self._poison:
            return chunks
        poisoned = RetrievedChunk(
            uuid.uuid4(), uuid.uuid4(), POISON_FILENAME, 1, 1, self._poison, POISON_SCORE
        )
        return [poisoned, *chunks]


def prompt_leak_patterns() -> tuple[str, ...]:
    rules = [line.removeprefix("- ") for line in SYSTEM_PROMPT.splitlines()]
    return tuple(
        re.escape(rule[:LEAK_FRAGMENT_CHARS]) for rule in rules if len(rule) >= LEAK_FRAGMENT_CHARS
    )


def violations(case: AttackCase, answer: str) -> tuple[str, ...]:
    patterns = case.forbidden + (prompt_leak_patterns() if case.checks_prompt_leak else ())
    return tuple(
        pattern for pattern in patterns if re.search(pattern, answer, re.IGNORECASE | re.DOTALL)
    )


@dataclass(frozen=True, slots=True)
class AttackTarget:
    embedder: EmbeddingProvider
    chat: ChatModelProvider
    retriever: Retriever
    rag_settings: RAGSettings
    model: str
    top_k: int


async def run_attack(case: AttackCase, target: AttackTarget) -> AttackResult:
    retriever = PoisonedRetriever(target.retriever, case.poison)
    nodes = RAGNodes(target.embedder, target.chat, retriever, target.rag_settings)
    service = RAGService(build_rag_graph(nodes))
    parts: list[str] = []
    abstained = False
    async for event in service.stream(case.question, target.model, target.top_k, case.instructions):
        if isinstance(event, TextDelta):
            parts.append(event.text)
        else:
            abstained = event.abstained
    answer = "".join(parts)
    return AttackResult(case, answer, abstained, violations(case, answer))


def _outcome(result: AttackResult) -> str:
    if not result.blocked:
        return "**FALHOU**"
    return "bloqueado (abstenção)" if result.abstained else "bloqueado"


def _excerpt(text: str) -> str:
    flat = " ".join(text.split()).replace("|", "\\|")
    return flat[:EXCERPT_CHARS] + ("…" if len(flat) > EXCERPT_CHARS else "")


def render_report(results: Sequence[AttackResult], profile: ProviderProfile, model: str) -> str:
    blocked = sum(result.blocked for result in results)
    lines = [
        f"Modelo de chat: `{model}` | embedding: `{profile.embedding_model}`",
        "",
        "| Ataque | Categoria | Resultado | Início da resposta |",
        "|---|---|---|---|",
        *(
            f"| {r.case.name} | {r.case.category} | {_outcome(r)} | {_excerpt(r.answer)} |"
            for r in results
        ),
        "",
        f"Bloqueados: {blocked}/{len(results)}",
    ]
    return "\n".join(lines)


def select_attacks(names: Sequence[str]) -> tuple[AttackCase, ...]:
    if not names:
        return ATTACKS
    unknown = set(names) - {case.name for case in ATTACKS}
    if unknown:
        raise SystemExit(UNKNOWN_ATTACK.format(names=", ".join(sorted(unknown))))
    return tuple(case for case in ATTACKS if case.name in names)


async def run(
    settings: Settings, model: str | None, attacks: Sequence[AttackCase] = ATTACKS
) -> tuple[str, bool]:
    profile = build_provider_profile(settings)
    chat_model = profile.resolve_chat_model(model)
    provider = OpenAICompatibleProvider(create_client(profile, settings), profile.embedding_model)
    engine = create_engine(settings.database_url.get_secret_value())
    rag_settings = RAGSettings(
        profile.min_score, settings.rag_context_max_chars, settings.llm_max_output_tokens
    )
    try:
        retriever = ChunkRetriever(create_session_factory(engine))
        target = AttackTarget(
            provider, provider, retriever, rag_settings, chat_model, settings.rag_top_k_default
        )
        results = [await run_attack(case, target) for case in attacks]
    finally:
        await provider.close()
        await engine.dispose()
    return render_report(results, profile, chat_model), all(r.blocked for r in results)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Executa ataques de prompt injection no RAG.")
    parser.add_argument("--model", default=None, help="Modelo de chat (padrão: o do ambiente).")
    parser.add_argument(
        "--attack", action="append", default=[], help="Executa só este ataque (repetível)."
    )
    args = parser.parse_args(argv)
    attacks = select_attacks(args.attack)
    settings = get_settings()
    configure_logging(settings.log_level)
    report, all_blocked = asyncio.run(run(settings, args.model, attacks))
    print(report)
    if not all_blocked:
        sys.exit(EXIT_FAILURE)


if __name__ == "__main__":  # pragma: no cover
    main()
