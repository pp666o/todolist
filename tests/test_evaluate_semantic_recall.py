from __future__ import annotations

import pytest

from scripts.evaluate_post_search import (
    EvaluationCase,
)
from scripts.evaluate_semantic_recall import (
    build_cutoff_metrics,
    build_experiment_summary,
    build_judged_ranks,
    grade3_hit_at_k,
    latency_summary,
    normalize_positive_values,
)


def make_case() -> EvaluationCase:
    return EvaluationCase(
        case_id="semantic_case",
        query="手机文件安全怎么办",
        top_k=5,
        recall_k=500,
        should_return_results=True,
        relevance={
            "a": 3,
            "b": 2,
            "c": 1,
        },
        binary_relevance_threshold=2,
    )


def test_normalize_positive_values_sorts_and_deduplicates() -> None:
    assert normalize_positive_values(
        [100, 20, 100, 50],
        name="cutoffs",
        maximum=500,
    ) == [
        20,
        50,
        100,
    ]


@pytest.mark.parametrize(
    "values",
    [
        [],
        [0, 20],
        [-1, 20],
        [20, 501],
    ],
)
def test_normalize_positive_values_rejects_invalid(
    values: list[int],
) -> None:
    with pytest.raises(ValueError):
        normalize_positive_values(
            values,
            name="cutoffs",
            maximum=500,
        )


def test_grade3_hit_at_k() -> None:
    relevance = {
        "anchor": 3,
        "related": 2,
    }

    assert grade3_hit_at_k(
        ["related", "anchor"],
        relevance,
        1,
    ) == 0.0

    assert grade3_hit_at_k(
        ["related", "anchor"],
        relevance,
        2,
    ) == 1.0


def test_grade3_hit_at_k_returns_none_without_anchor() -> None:
    assert grade3_hit_at_k(
        ["related"],
        {"related": 2},
        10,
    ) is None


def test_build_judged_ranks_includes_missing_items() -> None:
    ranks = build_judged_ranks(
        ["unjudged", "b", "a"],
        {
            "a": 3,
            "b": 2,
            "missing": 2,
            "weak": 1,
        },
        minimum_grade=2,
    )

    assert ranks == [
        {
            "source_id": "b",
            "grade": 2,
            "rank": 2,
        },
        {
            "source_id": "a",
            "grade": 3,
            "rank": 3,
        },
        {
            "source_id": "missing",
            "grade": 2,
            "rank": None,
        },
    ]


def test_build_cutoff_metrics_uses_binary_threshold() -> None:
    metrics = build_cutoff_metrics(
        ["c", "a", "x", "b"],
        make_case(),
        [1, 2, 4],
    )

    assert metrics["1"]["recall"] == 0.0
    assert metrics["2"]["recall"] == 0.5
    assert metrics["4"]["recall"] == 1.0

    assert metrics["1"]["mrr"] == 0.0
    assert metrics["2"]["mrr"] == 0.5
    assert metrics["4"]["mrr"] == 0.5

    assert metrics["1"]["grade3_hit"] == 0.0
    assert metrics["2"]["grade3_hit"] == 1.0


def test_latency_summary() -> None:
    summary = latency_summary(
        [1.0, 2.0, 3.0]
    )

    assert summary == {
        "count": 3,
        "mean": 2.0,
        "p50": 2.0,
        "p95": 2.9,
        "max": 3.0,
    }


def test_build_experiment_summary() -> None:
    summary = build_experiment_summary(
        [
            {
                "metrics": {
                    "20": {
                        "complete": True,
                        "returned_count": 20,
                        "recall": 0.5,
                        "mrr": 1.0,
                        "grade3_hit": 1.0,
                    }
                },
                "database_latency_ms": 4.0,
                "end_to_end_latency_ms": 10.0,
            },
            {
                "metrics": {
                    "20": {
                        "complete": True,
                        "returned_count": 20,
                        "recall": 1.0,
                        "mrr": 0.5,
                        "grade3_hit": 0.0,
                    }
                },
                "database_latency_ms": 6.0,
                "end_to_end_latency_ms": 12.0,
            },
        ],
        [20],
    )

    assert summary["case_count"] == 2
    assert summary["cutoffs"]["20"] == {
        "complete_case_count": 2,
        "incomplete_case_count": 0,
        "macro_recall": 0.75,
        "mrr": 0.75,
        "grade3_hit_rate": 0.5,
    }
    assert summary["database_latency_ms"]["mean"] == 5.0
    assert summary["end_to_end_latency_ms"]["mean"] == 11.0


def test_build_cutoff_metrics_marks_incomplete_cutoff() -> None:
    metrics = build_cutoff_metrics(
        ["a"],
        make_case(),
        [1, 2],
    )

    assert metrics["1"]["complete"] is True
    assert metrics["1"]["returned_count"] == 1

    assert metrics["2"] == {
        "complete": False,
        "returned_count": 1,
        "recall": None,
        "mrr": None,
        "grade3_hit": None,
    }
