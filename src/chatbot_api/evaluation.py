"""Retrieval evaluation: uv run python -m chatbot_api.evaluation [--top-k 4] [--dataset path]"""

import argparse
import asyncio
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from chatbot_api.core.config import Settings, get_settings
from chatbot_api.core.logging import configure_logging
from chatbot_api.db.session import create_engine, create_session_factory
from chatbot_api.providers.base import EmbeddingProvider
from chatbot_api.providers.openai_compatible import OpenAICompatibleProvider, create_client
from chatbot_api.providers.profile import build_provider_profile
from chatbot_api.rag.retrieval import ChunkRetriever, RetrievedChunk, Retriever

DEFAULT_DATASET = Path("evaluation/questions.json")
THRESHOLD_STEP = 0.005
MILLISECONDS = 1000
NO_RANK = 0


@dataclass(frozen=True, slots=True)
class EvalCase:
    question: str
    expected_terms: tuple[str, ...]

    @property
    def in_domain(self) -> bool:
        return bool(self.expected_terms)


@dataclass(frozen=True, slots=True)
class CaseResult:
    case: EvalCase
    top_score: float
    rank: int
    latency_ms: float


@dataclass(frozen=True, slots=True)
class Summary:
    threshold: float
    hit_rate: float
    mrr: float
    answered_in_domain: float
    abstained_out_of_domain: float
    mean_latency_ms: float

    @property
    def balanced_accuracy(self) -> float:
        return (self.answered_in_domain + self.abstained_out_of_domain) / 2


def load_cases(path: Path) -> list[EvalCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        EvalCase(item["question"], tuple(term.lower() for term in item.get("expected_terms", [])))
        for item in raw["cases"]
    ]


def relevant_rank(case: EvalCase, chunks: Sequence[RetrievedChunk]) -> int:
    for rank, chunk in enumerate(chunks, start=1):
        content = chunk.content.lower()
        if any(term in content for term in case.expected_terms):
            return rank
    return NO_RANK


async def evaluate_cases(
    cases: Sequence[EvalCase], embedder: EmbeddingProvider, retriever: Retriever, top_k: int
) -> list[CaseResult]:
    vectors = await embedder.embed([case.question for case in cases])
    results: list[CaseResult] = []
    for case, vector in zip(cases, vectors, strict=True):
        started = time.perf_counter()
        chunks = await retriever.search(vector, embedder.embedding_model, top_k)
        latency = (time.perf_counter() - started) * MILLISECONDS
        top_score = chunks[0].score if chunks else 0.0
        results.append(CaseResult(case, top_score, relevant_rank(case, chunks), latency))
    return results


def _ratio(count: float, total: int) -> float:
    return count / total if total else 0.0


def summarize(results: Sequence[CaseResult], threshold: float) -> Summary:
    inside = [result for result in results if result.case.in_domain]
    outside = [result for result in results if not result.case.in_domain]
    hits = [result for result in inside if result.rank != NO_RANK]
    return Summary(
        threshold=threshold,
        hit_rate=_ratio(len(hits), len(inside)),
        mrr=_ratio(sum(1 / result.rank for result in hits), len(inside)) if hits else 0.0,
        answered_in_domain=_ratio(sum(r.top_score >= threshold for r in inside), len(inside)),
        abstained_out_of_domain=_ratio(sum(r.top_score < threshold for r in outside), len(outside)),
        mean_latency_ms=_ratio(sum(r.latency_ms for r in results), len(results)),
    )


def best_threshold(results: Sequence[CaseResult]) -> Summary:
    """Highest balanced accuracy; ties go to the lowest threshold (fewer false abstentions)."""
    steps = int(1 / THRESHOLD_STEP) + 1
    candidates = [summarize(results, round(step * THRESHOLD_STEP, 3)) for step in range(steps)]
    return max(candidates, key=lambda summary: (summary.balanced_accuracy, -summary.threshold))


def render_report(
    results: Sequence[CaseResult], current: Summary, best: Summary, top_k: int
) -> str:
    lines = [
        f"| Pergunta | No escopo | Top-1 | Rank relevante (top-{top_k}) |",
        "|---|---|---|---|",
        *(
            f"| {r.case.question} | {'sim' if r.case.in_domain else 'não'} | {r.top_score:.3f} | "
            f"{r.rank or '-' if r.case.in_domain else 'n/a'} |"
            for r in results
        ),
        "",
        "| Métrica | Limiar atual | Melhor limiar |",
        "|---|---|---|",
        f"| Limiar | {current.threshold:.3f} | {best.threshold:.3f} |",
        f"| Hit@{top_k} (recall) | {current.hit_rate:.0%} | {best.hit_rate:.0%} |",
        f"| MRR | {current.mrr:.3f} | {best.mrr:.3f} |",
        f"| Respondidas no escopo | {current.answered_in_domain:.0%} | "
        f"{best.answered_in_domain:.0%} |",
        f"| Abstenção fora do escopo | {current.abstained_out_of_domain:.0%} | "
        f"{best.abstained_out_of_domain:.0%} |",
        f"| Latência média do retrieval | {current.mean_latency_ms:.1f} ms | - |",
    ]
    return "\n".join(lines)


async def run(dataset: Path, top_k: int, settings: Settings) -> str:
    profile = build_provider_profile(settings)
    provider = OpenAICompatibleProvider(create_client(profile, settings), profile.embedding_model)
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        retriever = ChunkRetriever(create_session_factory(engine))
        results = await evaluate_cases(load_cases(dataset), provider, retriever, top_k)
    finally:
        await provider.close()
        await engine.dispose()
    header = f"Modelo de embedding: `{profile.embedding_model}`\n\n"
    return header + render_report(
        results, summarize(results, profile.min_score), best_threshold(results), top_k
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Avalia o retrieval com perguntas versionadas.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--top-k", type=int, default=None)
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    print(asyncio.run(run(args.dataset, args.top_k or settings.rag_top_k_default, settings)))


if __name__ == "__main__":  # pragma: no cover
    main()
