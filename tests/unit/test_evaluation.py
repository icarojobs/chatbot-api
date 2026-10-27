import json
import uuid
from pathlib import Path

import pytest

from chatbot_api import evaluation
from chatbot_api.core.config import Settings
from chatbot_api.evaluation import (
    CaseResult,
    EvalCase,
    best_threshold,
    evaluate_cases,
    load_cases,
    relevant_rank,
    render_report,
    summarize,
)
from chatbot_api.rag.retrieval import RetrievedChunk
from tests.fakes import FakeEmbeddingProvider, FakeRetriever

IN_DOMAIN = EvalCase("O que é matriciamento?", ("matriciamento",))
OUT_OF_DOMAIN = EvalCase("Qual a capital da Austrália?", ())


def chunk(content: str, score: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(uuid.uuid4(), uuid.uuid4(), "a.pdf", 1, 1, content, score)


def result(case: EvalCase, top_score: float, rank: int) -> CaseResult:
    return CaseResult(case, top_score, rank, latency_ms=2.0)


def test_loads_dataset_with_lowercase_terms(tmp_path: Path) -> None:
    dataset = tmp_path / "questions.json"
    dataset.write_text(
        json.dumps({"cases": [{"question": "q1", "expected_terms": ["CAPS"]}, {"question": "q2"}]}),
        encoding="utf-8",
    )

    cases = load_cases(dataset)

    assert cases == [EvalCase("q1", ("caps",)), EvalCase("q2", ())]
    assert [case.in_domain for case in cases] == [True, False]


def test_versioned_dataset_is_balanced() -> None:
    cases = load_cases(evaluation.DEFAULT_DATASET)

    assert sum(case.in_domain for case in cases) == 20
    assert sum(not case.in_domain for case in cases) == 10


def test_relevant_rank_is_first_chunk_with_expected_term() -> None:
    chunks = [chunk("outro assunto"), chunk("O Matriciamento envolve equipes")]

    assert relevant_rank(IN_DOMAIN, chunks) == 2
    assert relevant_rank(IN_DOMAIN, [chunk("nada")]) == 0


async def test_evaluates_cases_with_retriever() -> None:
    retriever = FakeRetriever([0.8])

    results = await evaluate_cases([IN_DOMAIN], FakeEmbeddingProvider(), retriever, top_k=3)

    assert results[0].top_score == 0.8
    assert results[0].rank == 0
    assert retriever.calls == [("fake-embedding", 3)]


async def test_empty_retrieval_scores_zero() -> None:
    results = await evaluate_cases([OUT_OF_DOMAIN], FakeEmbeddingProvider(), FakeRetriever([]), 4)

    assert results[0].top_score == 0.0


def test_summarizes_metrics_for_threshold() -> None:
    results = [
        result(IN_DOMAIN, 0.6, 1),
        result(IN_DOMAIN, 0.35, 2),
        result(IN_DOMAIN, 0.5, 0),
        result(OUT_OF_DOMAIN, 0.2, 0),
        result(OUT_OF_DOMAIN, 0.4, 0),
    ]

    summary = summarize(results, threshold=0.38)

    assert summary.hit_rate == pytest.approx(2 / 3)
    assert summary.mrr == pytest.approx((1 + 0.5) / 3)
    assert summary.answered_in_domain == pytest.approx(2 / 3)
    assert summary.abstained_out_of_domain == pytest.approx(0.5)
    assert summary.mean_latency_ms == 2.0
    assert summary.balanced_accuracy == pytest.approx((2 / 3 + 0.5) / 2)


def test_summary_without_hits_or_cases() -> None:
    summary = summarize([], threshold=0.5)

    assert (summary.hit_rate, summary.mrr, summary.answered_in_domain) == (0.0, 0.0, 0.0)


def test_best_threshold_separates_groups_preferring_lowest() -> None:
    results = [result(IN_DOMAIN, 0.6, 1), result(OUT_OF_DOMAIN, 0.3, 0)]

    best = best_threshold(results)

    assert best.balanced_accuracy == 1.0
    assert best.threshold == pytest.approx(0.305)


def test_renders_markdown_report() -> None:
    results = [result(IN_DOMAIN, 0.6, 1), result(OUT_OF_DOMAIN, 0.3, 0)]

    report = render_report(results, summarize(results, 0.5), best_threshold(results), top_k=4)

    assert "| O que é matriciamento? | sim | 0.600 | 1 |" in report
    assert "| Qual a capital da Austrália? | não | 0.300 | n/a |" in report
    assert "| Hit@4 (recall) | 100% | 100% |" in report


def test_main_prints_report(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    session_factory: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(evaluation, "get_settings", lambda: settings)
    monkeypatch.setattr(
        evaluation, "OpenAICompatibleProvider", lambda _client, model: FakeEmbeddingProvider(model)
    )

    evaluation.main(["--top-k", "2"])

    output = capsys.readouterr().out
    assert "Modelo de embedding: `bge-m3:567m`" in output
    assert "| Hit@2 (recall) | 0% |" in output
