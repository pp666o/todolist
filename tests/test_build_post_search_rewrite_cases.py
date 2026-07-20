"""Tests for the formal rewrite evaluation dataset builder."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import build_post_search_rewrite_cases as builder


def make_draft(
    *,
    draft_id: str = "draft_001",
    query_type: str = "content_intent",
) -> dict[str, str]:
    return {
        "draft_id": draft_id,
        "anchor_source_id": "anchor-1",
        "category": "问答",
        "city": "银川市",
        "district": "西夏区",
        "latitude": "38.49482",
        "longitude": "106.119637",
        "query": "手机文件安全怎么处理",
        "query_type": query_type,
        "review_status": "query_drafted",
    }


def make_candidate(
    source_id: str,
    *,
    rank: int | None,
    grade: int,
    is_anchor: bool = False,
) -> dict[str, str]:
    return {
        "draft_id": "draft_001",
        "candidate_rank": (
            "" if rank is None else str(rank)
        ),
        "candidate_source_id": source_id,
        "candidate_origin": (
            "injected_anchor"
            if rank is None
            else "search_result"
        ),
        "is_anchor": "yes" if is_anchor else "no",
        "relevance_grade": str(grade),
        "review_status": "assistant_reviewed",
    }


def make_candidates() -> list[dict[str, str]]:
    return [
        make_candidate("result-1", rank=1, grade=1),
        make_candidate("result-2", rank=2, grade=2),
        make_candidate("result-3", rank=3, grade=0),
        make_candidate("anchor-1", rank=None, grade=3, is_anchor=True),
    ]


def test_select_compact_candidates_injects_anchor() -> None:
    selected = builder.select_compact_candidates(
        make_candidates(),
        top_k=2,
    )

    assert [
        row["candidate_source_id"]
        for row in selected
    ] == [
        "result-1",
        "result-2",
        "anchor-1",
    ]


def test_build_case_uses_binary_threshold_two() -> None:
    case = builder.build_case(
        make_draft(),
        make_candidates(),
        top_k=2,
        recall_k=1000,
        binary_relevance_threshold=2,
        radius_km=20.0,
    )

    assert case["binary_relevance_threshold"] == 2
    assert case["relevance"] == {
        "result-1": 1,
        "result-2": 2,
        "anchor-1": 3,
    }
    assert "city" not in case
    assert "category" not in case


def test_geo_case_includes_geo_constraints() -> None:
    case = builder.build_case(
        make_draft(query_type="geo_intent"),
        make_candidates(),
        top_k=2,
        recall_k=1000,
        binary_relevance_threshold=2,
        radius_km=20.0,
    )

    assert case["city"] == "银川市"
    assert case["district"] == "西夏区"
    assert case["latitude"] == 38.49482
    assert case["longitude"] == 106.119637
    assert case["radius_km"] == 20.0


def test_category_case_includes_category() -> None:
    case = builder.build_case(
        make_draft(query_type="category_intent"),
        make_candidates(),
        top_k=2,
        recall_k=1000,
        binary_relevance_threshold=2,
        radius_km=20.0,
    )

    assert case["category"] == "问答"


def test_unreviewed_candidate_is_rejected() -> None:
    candidates = make_candidates()
    candidates[0]["review_status"] = "unjudged"

    with pytest.raises(
        ValueError,
        match="not reviewed",
    ):
        builder.build_case(
            make_draft(),
            candidates,
            top_k=2,
            recall_k=1000,
            binary_relevance_threshold=2,
            radius_km=20.0,
        )


def test_write_jsonl_refuses_overwrite(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text("existing\n", encoding="utf-8")

    with pytest.raises(
        FileExistsError,
        match="--overwrite",
    ):
        builder.write_jsonl(
            path,
            [],
            overwrite=False,
        )
