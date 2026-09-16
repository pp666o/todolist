"""Tests for the offline post-search evaluator."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from todolist.app.features.post_search.post_search import (
    PostSearchHit,
    PostSearchResponse,
)
from scripts import evaluate_post_search as evaluation


def make_case(**overrides):
    payload = {
        "case_id": "case-1",
        "query": "电脑维修",
        "top_k": 3,
        "recall_k": 10,
        "should_return_results": True,
        "relevance": {
            "a": 3,
            "b": 1,
        },
    }
    payload.update(overrides)
    return evaluation.EvaluationCase.model_validate(payload)


def make_hit(
    source_id: str,
    *,
    distance_km: float | None = None,
) -> PostSearchHit:
    return PostSearchHit(
        post_id=1,
        source="mysql_tiezi_geo_new",
        source_id=source_id,
        title=f"title-{source_id}",
        content="content",
        category="求助",
        score=1.0,
        text_score=1.0,
        geo_score=1.0,
        hot_score=0.0,
        unlock_score=0.0,
        distance_km=distance_km,
    )


def make_response(
    source_ids: list[str],
    *,
    degraded: bool = False,
) -> PostSearchResponse:
    return PostSearchResponse(
        request_id="request-1",
        query="电脑维修",
        total_candidates=len(source_ids),
        result_count=len(source_ids),
        items=[
            make_hit(source_id)
            for source_id in source_ids
        ],
        degraded=degraded,
        degraded_reason=(
            "Redis unavailable"
            if degraded
            else None
        ),
    )


def test_binary_ranking_metrics() -> None:
    relevance = {
        "a": 3,
        "b": 1,
        "c": 0,
    }
    returned = ["x", "a", "b"]

    assert evaluation.precision_at_k(
        returned,
        relevance,
        3,
    ) == pytest.approx(2 / 3)

    assert evaluation.recall_at_k(
        returned,
        relevance,
        3,
    ) == 1.0

    assert evaluation.reciprocal_rank_at_k(
        returned,
        relevance,
        3,
    ) == 0.5


def test_ndcg_rewards_better_ordering() -> None:
    relevance = {
        "a": 3,
        "b": 1,
    }

    ideal = evaluation.ndcg_at_k(
        ["a", "b"],
        relevance,
        2,
    )
    reversed_order = evaluation.ndcg_at_k(
        ["b", "a"],
        relevance,
        2,
    )

    assert ideal == 1.0
    assert reversed_order is not None
    assert reversed_order < ideal


def test_negative_case_metrics_are_undefined() -> None:
    assert evaluation.precision_at_k(
        [],
        {},
        10,
    ) is None
    assert evaluation.recall_at_k(
        [],
        {},
        10,
    ) is None
    assert evaluation.reciprocal_rank_at_k(
        [],
        {},
        10,
    ) is None
    assert evaluation.ndcg_at_k(
        [],
        {},
        10,
    ) is None


def test_percentile_interpolates() -> None:
    values = [10.0, 20.0, 30.0, 40.0]

    assert evaluation.percentile(
        values,
        50,
    ) == 25.0

    assert evaluation.percentile(
        values,
        95,
    ) == pytest.approx(38.5)


def test_load_cases_rejects_duplicate_ids(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cases.jsonl"

    row = {
        "case_id": "duplicate",
        "query": "测试",
        "should_return_results": True,
        "relevance": {
            "1": 3,
        },
    }

    path.write_text(
        json.dumps(row, ensure_ascii=False)
        + "\n"
        + json.dumps(row, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="Duplicate case_id",
    ):
        evaluation.load_cases(path)


def test_positive_case_requires_judgment() -> None:
    with pytest.raises(
        ValueError,
        match="positive case requires",
    ):
        evaluation.EvaluationCase(
            case_id="invalid",
            query="测试",
            should_return_results=True,
            relevance={},
        )


def test_evaluate_case_uses_source_id() -> None:
    case = make_case(
        relevance={
            "a": 3,
        }
    )

    async def fake_search(_):
        return make_response(["a", "x"])

    result = asyncio.run(
        evaluation.evaluate_case(
            case,
            search=fake_search,
            repeat=2,
        )
    )

    assert result["success"] is True
    assert result["returned_source_ids"] == ["a", "x"]
    assert result["relevant_ranks"] == {
        "a": 1,
    }
    assert result["recall_at_k"] == 1.0
    assert result["mrr_at_k"] == 1.0
    assert result[
        "ranking_stable_across_repeats"
    ] is True
    assert len(result["latency_ms"]) == 2


def test_geo_range_hit_rate() -> None:
    case = make_case(
        latitude=30.0,
        longitude=120.0,
        radius_km=10.0,
        relevance={
            "a": 3,
        },
    )

    async def fake_search(_):
        response = make_response([])

        response.items = [
            make_hit(
                "a",
                distance_km=2.0,
            ),
            make_hit(
                "x",
                distance_km=12.0,
            ),
        ]
        response.result_count = 2
        response.total_candidates = 2

        return response

    result = asyncio.run(
        evaluation.evaluate_case(
            case,
            search=fake_search,
            repeat=1,
        )
    )

    assert result["geo_hits"] == 1
    assert result["geo_evaluated_items"] == 2
    assert result["geo_range_hit_rate"] == 0.5


def test_forced_degradation_summary() -> None:
    results = [
        {
            "success": True,
            "should_return_results": True,
            "result_count": 1,
            "result_presence_matches": True,
            "precision_at_k": 1.0,
            "recall_at_k": 1.0,
            "mrr_at_k": 1.0,
            "ndcg_at_k": 1.0,
            "geo_hits": 1,
            "geo_evaluated_items": 1,
            "degraded": True,
            "ranking_stable_across_repeats": True,
            "latency_ms": [10.0],
        }
    ]

    summary = evaluation.build_summary(
        results,
        redis_mode="forced-failure",
    )

    assert summary[
        "redis_degradation_success_rate"
    ] == 1.0
    assert summary["request_success_rate"] == 1.0
    assert summary["geo_range_hit_rate"] == 1.0


def test_binary_relevance_threshold_defaults_to_one() -> None:
    case = evaluation.EvaluationCase(
        case_id="default-threshold",
        query="默认阈值",
        should_return_results=True,
        relevance={
            "weak": 1,
        },
    )

    assert case.binary_relevance_threshold == 1


def test_binary_metrics_respect_relevance_threshold() -> None:
    returned = [
        "weak",
        "strong",
    ]
    relevance = {
        "weak": 1,
        "strong": 2,
        "best": 3,
    }

    assert evaluation.precision_at_k(
        returned,
        relevance,
        2,
        2,
    ) == 0.5

    assert evaluation.recall_at_k(
        returned,
        relevance,
        2,
        2,
    ) == 0.5

    assert evaluation.reciprocal_rank_at_k(
        returned,
        relevance,
        2,
        2,
    ) == 0.5


def test_grade_one_still_participates_in_ndcg() -> None:
    relevance = {
        "weak": 1,
        "strong": 2,
    }

    score = evaluation.ndcg_at_k(
        ["weak", "strong"],
        relevance,
        2,
    )

    assert score is not None
    assert 0 < score < 1


def test_positive_case_requires_grade_meeting_threshold() -> None:
    with pytest.raises(
        ValueError,
        match="binary_relevance_threshold",
    ):
        evaluation.EvaluationCase(
            case_id="insufficient-grade",
            query="只有弱相关",
            should_return_results=True,
            binary_relevance_threshold=2,
            relevance={
                "weak": 1,
            },
        )


def test_positive_case_accepts_grade_meeting_threshold() -> None:
    case = evaluation.EvaluationCase(
        case_id="sufficient-grade",
        query="存在有效相关",
        should_return_results=True,
        binary_relevance_threshold=2,
        relevance={
            "weak": 1,
            "strong": 2,
        },
    )

    assert case.binary_relevance_threshold == 2
