from __future__ import annotations

import argparse
import asyncio
import sys

import pytest

import scripts.evaluate_semantic_recall as semantic_evaluator

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
    overfetch_factor,
    parse_args,
    retrieve_semantic_candidates,
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



def test_experiment_summary_includes_returned_count() -> None:
    summary = build_experiment_summary(
        [
            {
                "metrics": {
                    "20": {
                        "complete": False,
                        "returned_count": 10,
                        "recall": None,
                        "mrr": None,
                        "grade3_hit": None,
                    }
                },
                "returned_count": 10,
                "database_latency_ms": 1.0,
                "end_to_end_latency_ms": 2.0,
            },
            {
                "metrics": {
                    "20": {
                        "complete": True,
                        "returned_count": 20,
                        "recall": 1.0,
                        "mrr": 1.0,
                        "grade3_hit": 1.0,
                    }
                },
                "returned_count": 20,
                "database_latency_ms": 2.0,
                "end_to_end_latency_ms": 3.0,
            },
        ],
        [20],
    )

    assert summary["returned_count"] == {
        "count": 2,
        "min": 10,
        "mean": 15.0,
        "p50": 15.0,
        "max": 20,
    }


def test_global_retrieval_dispatches_to_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_global(
        connection: object,
        **kwargs: object,
    ) -> list[dict[str, object]]:
        calls.append(
            {
                "connection": connection,
                **kwargs,
            }
        )
        return [
            {
                "source_id": "a",
            }
        ]

    async def fail_filtered(
        connection: object,
        **kwargs: object,
    ) -> list[dict[str, object]]:
        raise AssertionError(
            "filtered recall must not be called"
        )

    monkeypatch.setattr(
        semantic_evaluator,
        "semantic_search_global",
        fake_global,
    )
    monkeypatch.setattr(
        semantic_evaluator,
        "semantic_search_filtered",
        fail_filtered,
    )

    connection = object()
    embedding = [0.1, 0.2]

    result = asyncio.run(
        retrieve_semantic_candidates(
            connection,
            mode="global",
            case=make_case(),
            query_embedding=embedding,
            limit=200,
            ef_search=100,
        )
    )

    assert result == [
        {
            "source_id": "a",
        }
    ]
    assert calls == [
        {
            "connection": connection,
            "query_embedding": embedding,
            "limit": 200,
            "ef_search": 100,
        }
    ]


def test_filtered_retrieval_maps_case_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_filtered(
        connection: object,
        **kwargs: object,
    ) -> list[dict[str, object]]:
        captured.update(kwargs)
        return [
            {
                "source_id": "geo-post",
            }
        ]

    async def fail_global(
        connection: object,
        **kwargs: object,
    ) -> list[dict[str, object]]:
        raise AssertionError(
            "global recall must not be called"
        )

    monkeypatch.setattr(
        semantic_evaluator,
        "semantic_search_filtered",
        fake_filtered,
    )
    monkeypatch.setattr(
        semantic_evaluator,
        "semantic_search_global",
        fail_global,
    )

    case = EvaluationCase(
        case_id="filtered_case",
        query="附近有什么可以吐槽的",
        top_k=5,
        recall_k=200,
        category="吐槽",
        visible_statuses=[
            "visible",
            "reviewing",
        ],
        city="济南市",
        district="市中区",
        latitude=36.613094,
        longitude=117.033028,
        radius_km=20.0,
        should_return_results=True,
        relevance={
            "geo-post": 3,
        },
        binary_relevance_threshold=2,
    )

    embedding = [0.1, 0.2]

    result = asyncio.run(
        retrieve_semantic_candidates(
            object(),
            mode="filtered",
            case=case,
            query_embedding=embedding,
            limit=200,
            ef_search=500,
            iterative_scan="strict_order",
            radius_overfetch_factor=2.0,
        )
    )

    assert result == [
        {
            "source_id": "geo-post",
        }
    ]

    assert captured == {
        "query_embedding": embedding,
        "category": "吐槽",
        "visible_statuses": [
            "visible",
            "reviewing",
        ],
        "city": "济南市",
        "district": "市中区",
        "latitude": 36.613094,
        "longitude": 117.033028,
        "radius_km": 20.0,
        "radius_overfetch_factor": 2.0,
        "limit": 200,
        "ef_search": 500,
        "iterative_scan": "strict_order",
    }


def test_filtered_retrieval_passes_empty_optional_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_filtered(
        connection: object,
        **kwargs: object,
    ) -> list[dict[str, object]]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        semantic_evaluator,
        "semantic_search_filtered",
        fake_filtered,
    )

    asyncio.run(
        retrieve_semantic_candidates(
            object(),
            mode="filtered",
            case=make_case(),
            query_embedding=[0.1],
            limit=20,
            ef_search=40,
        )
    )

    assert captured["category"] is None
    assert captured["visible_statuses"] == []
    assert captured["city"] is None
    assert captured["district"] is None
    assert captured["latitude"] is None
    assert captured["longitude"] is None
    assert captured["radius_km"] is None


def test_retrieval_rejects_unknown_mode() -> None:
    with pytest.raises(
        ValueError,
        match="unsupported semantic evaluation mode",
    ):
        asyncio.run(
            retrieve_semantic_candidates(
                object(),
                mode="unknown",
                case=make_case(),
                query_embedding=[0.1],
                limit=20,
                ef_search=40,
            )
        )


def test_parse_args_defaults_to_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_semantic_recall.py",
        ],
    )

    args = parse_args()

    assert args.mode == "global"
    assert args.iterative_scan == "strict_order"
    assert args.radius_overfetch_factor == 2.0
    assert args.output is None


def test_parse_args_accepts_filtered_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_semantic_recall.py",
            "--mode",
            "filtered",
            "--iterative-scan",
            "strict_order",
            "--radius-overfetch-factor",
            "3.0",
        ],
    )

    args = parse_args()

    assert args.mode == "filtered"
    assert args.iterative_scan == "strict_order"
    assert args.radius_overfetch_factor == 3.0


@pytest.mark.parametrize(
    "value",
    [
        "0",
        "0.5",
        "-1",
    ],
)
def test_overfetch_factor_rejects_values_below_one(
    value: str,
) -> None:
    with pytest.raises(
        argparse.ArgumentTypeError,
    ):
        overfetch_factor(value)


def test_parse_args_rejects_invalid_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_semantic_recall.py",
            "--mode",
            "hybrid",
        ],
    )

    with pytest.raises(SystemExit):
        parse_args()
