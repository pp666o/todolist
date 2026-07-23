"""Tests for recall-route marginal coverage evaluation."""

from __future__ import annotations

import asyncio

import pytest

from scripts.evaluate_post_search import (
    EvaluationCase,
)
from scripts.evaluate_recall_route_coverage import (
    analyze_case_routes,
    coverage_metrics,
    marginal_metrics,
    normalize_positive_values,
    ordered_candidate_keys,
    overlap_metrics,
    retrieve_freshness_candidates,
    summarize_case_results,
)


def make_case(
    **overrides,
) -> EvaluationCase:
    payload = {
        "case_id": "route_case",
        "query": "手机文件安全怎么办",
        "top_k": 5,
        "recall_k": 200,
        "should_return_results": True,
        "relevance": {
            "a": 3,
            "c": 2,
            "d": 3,
            "weak": 1,
        },
        "binary_relevance_threshold": 2,
    }
    payload.update(overrides)

    return EvaluationCase.model_validate(
        payload
    )


def candidate(
    source_id: str,
    *,
    source: str = "mysql",
) -> dict[str, str]:
    return {
        "source": source,
        "source_id": source_id,
    }


def test_normalize_positive_values() -> None:
    assert normalize_positive_values(
        [100, 20, 100],
        name="cutoffs",
        maximum=200,
    ) == [
        20,
        100,
    ]


@pytest.mark.parametrize(
    "values",
    [
        [],
        [0],
        [-1, 20],
        [20, 201],
    ],
)
def test_normalize_positive_values_rejects_invalid(
    values: list[int],
) -> None:
    with pytest.raises(ValueError):
        normalize_positive_values(
            values,
            name="cutoffs",
            maximum=200,
        )


def test_ordered_candidate_keys_uses_business_key() -> None:
    keys = ordered_candidate_keys(
        [
            candidate("1", source="mysql-a"),
            candidate("1", source="mysql-b"),
            candidate("1", source="mysql-a"),
        ]
    )

    assert keys == [
        ("mysql-a", "1"),
        ("mysql-b", "1"),
    ]


def test_combined_coverage_uses_route_top_k_union() -> None:
    case = make_case()

    route_keys = {
        "freshness": [
            ("mysql", "a"),
            ("mysql", "b"),
        ],
        "lexical": [
            ("mysql", "b"),
            ("mysql", "c"),
        ],
        "semantic": [
            ("mysql", "c"),
            ("mysql", "d"),
        ],
    }

    metrics = coverage_metrics(
        route_names=(
            "freshness",
            "lexical",
            "semantic",
        ),
        route_keys=route_keys,
        case=case,
        cutoff=2,
    )

    assert metrics["candidate_count"] == 4
    assert metrics["relevant_hit_count"] == 3
    assert metrics["relevant_source_ids"] == [
        "a",
        "c",
        "d",
    ]
    assert metrics["recall"] == 1.0
    assert metrics["grade3_hit"] == 1.0


def test_overlap_metrics() -> None:
    metrics = overlap_metrics(
        left_keys=[
            ("mysql", "a"),
            ("mysql", "b"),
        ],
        right_keys=[
            ("mysql", "b"),
            ("mysql", "c"),
        ],
        cutoff=2,
    )

    assert metrics == {
        "left_candidate_count": 2,
        "right_candidate_count": 2,
        "intersection_count": 1,
        "union_count": 3,
        "jaccard": pytest.approx(
            1 / 3
        ),
    }


def test_marginal_metrics_identifies_new_hits() -> None:
    case = make_case()

    route_keys = {
        "freshness": [
            ("mysql", "a"),
            ("mysql", "b"),
        ],
        "lexical": [
            ("mysql", "b"),
            ("mysql", "c"),
        ],
        "semantic": [
            ("mysql", "c"),
            ("mysql", "d"),
        ],
    }

    lexical = marginal_metrics(
        additional_route="lexical",
        baseline_routes=("freshness",),
        route_keys=route_keys,
        case=case,
        cutoff=2,
    )

    assert lexical["candidate_count"] == 1
    assert lexical["relevant_source_ids"] == [
        "c"
    ]
    assert lexical["grade3_source_ids"] == []

    semantic = marginal_metrics(
        additional_route="semantic",
        baseline_routes=(
            "freshness",
            "lexical",
        ),
        route_keys=route_keys,
        case=case,
        cutoff=2,
    )

    assert semantic["candidate_count"] == 1
    assert semantic["relevant_source_ids"] == [
        "d"
    ]
    assert semantic["grade3_source_ids"] == [
        "d"
    ]


def test_analyze_and_summarize_case_routes() -> None:
    result = analyze_case_routes(
        case=make_case(),
        route_candidates={
            "freshness": [
                candidate("a"),
                candidate("b"),
            ],
            "lexical": [
                candidate("b"),
                candidate("c"),
            ],
            "semantic": [
                candidate("c"),
                candidate("d"),
            ],
        },
        cutoffs=[2],
        latency_ms={
            "freshness": 1.0,
            "lexical": 2.0,
            "semantic_end_to_end": 3.0,
        },
    )

    assert (
        result["coverage"]["routes"]
        ["freshness"]["2"]["recall"]
        == pytest.approx(1 / 3)
    )
    assert (
        result["coverage"]["combinations"]
        ["freshness_lexical_semantic"]
        ["2"]["recall"]
        == 1.0
    )

    summary = summarize_case_results(
        [result],
        [2],
    )

    assert (
        summary["routes"]["lexical"]["2"]
        ["macro_recall"]
        == pytest.approx(1 / 3)
    )
    assert (
        summary["combinations"]
        ["freshness_lexical_semantic"]
        ["2"]["macro_recall"]
        == 1.0
    )
    assert (
        summary["marginals"]["2"]
        ["lexical_over_freshness"]
        ["unique_new_relevant_source_ids"]
        == ["c"]
    )
    assert (
        summary["marginals"]["2"]
        ["semantic_over_freshness_lexical"]
        ["unique_new_grade3_source_ids"]
        == ["d"]
    )
    assert (
        summary["latency_ms"]["lexical"]
        ["mean"]
        == 2.0
    )


class FakeRepository:
    def __init__(
        self,
        rows: list[dict[str, object]],
    ) -> None:
        self.rows = rows
        self.captured: dict[str, object] = {}

    async def search_candidates(
        self,
        **kwargs,
    ) -> list[dict[str, object]]:
        self.captured.update(kwargs)
        return self.rows


def test_freshness_retrieval_maps_filters_and_radius() -> None:
    repository = FakeRepository(
        [
            {
                "source": "mysql",
                "source_id": "near",
                "latitude": 0.1,
                "longitude": 0.0,
            },
            {
                "source": "mysql",
                "source_id": "far",
                "latitude": 1.0,
                "longitude": 0.0,
            },
        ]
    )

    case = make_case(
        category="求助",
        city="测试市",
        district="测试区",
        latitude=0.0,
        longitude=0.0,
        radius_km=20.0,
    )

    result = asyncio.run(
        retrieve_freshness_candidates(
            repository,
            case=case,
            limit=200,
        )
    )

    assert [
        row["source_id"]
        for row in result
    ] == [
        "near"
    ]

    assert repository.captured[
        "category"
    ] == "求助"
    assert repository.captured[
        "city"
    ] == "测试市"
    assert repository.captured[
        "district"
    ] == "测试区"
    assert repository.captured[
        "limit"
    ] == 200

    assert repository.captured[
        "min_latitude"
    ] is not None
    assert repository.captured[
        "max_latitude"
    ] is not None
    assert repository.captured[
        "min_longitude"
    ] is not None
    assert repository.captured[
        "max_longitude"
    ] is not None

    assert result[0]["distance_km"] == (
        pytest.approx(
            11.119,
            rel=0.01,
        )
    )
