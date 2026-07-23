"""Tests for fixed-budget recall allocation evaluation."""

from __future__ import annotations

import pytest

from scripts.evaluate_recall_budget_allocations import (
    allocation_name,
    evaluate_case_allocation,
    normalize_route_keys,
    parse_allocation,
    summarize_allocation,
    weighted_rank_merge,
)


def key(
    source_id: str,
    source: str = "mysql",
) -> tuple[str, str]:
    return source, source_id


def test_parse_allocation() -> None:
    allocation = parse_allocation(
        "100,50,50",
        total_budget=200,
    )

    assert allocation == {
        "freshness": 100,
        "lexical": 50,
        "semantic": 50,
    }
    assert (
        allocation_name(allocation)
        == "f100_l50_s50"
    )


@pytest.mark.parametrize(
    "value",
    [
        "100,100",
        "100,50,49",
        "100,-1,101",
        "a,50,150",
    ],
)
def test_parse_allocation_rejects_invalid(
    value: str,
) -> None:
    with pytest.raises(ValueError):
        parse_allocation(
            value,
            total_budget=200,
        )


def test_weighted_merge_respects_allocation() -> None:
    result = weighted_rank_merge(
        route_keys={
            "freshness": [
                key("f1"),
                key("f2"),
                key("f3"),
                key("f4"),
                key("f5"),
            ],
            "lexical": [
                key("l1"),
                key("l2"),
                key("l3"),
            ],
            "semantic": [
                key("s1"),
            ],
        },
        allocation={
            "freshness": 4,
            "lexical": 2,
            "semantic": 0,
        },
        total_budget=6,
    )

    assert result["candidate_count"] == 6
    assert result["contribution_count"] == {
        "freshness": 4,
        "lexical": 2,
        "semantic": 0,
    }

    assert all(
        candidate["selected_from"]
        != "semantic"
        for candidate in result["candidates"]
    )


def test_weighted_merge_backfills_duplicates() -> None:
    result = weighted_rank_merge(
        route_keys={
            "freshness": [
                key("shared"),
                key("f2"),
                key("f3"),
                key("f4"),
            ],
            "lexical": [
                key("shared"),
                key("l2"),
                key("l3"),
                key("l4"),
            ],
            "semantic": [],
        },
        allocation={
            "freshness": 2,
            "lexical": 2,
            "semantic": 0,
        },
        total_budget=4,
    )

    assert result["candidate_count"] == 4

    selected_keys = {
        (
            candidate["source"],
            candidate["source_id"],
        )
        for candidate in result["candidates"]
    }

    assert len(selected_keys) == 4
    assert result["fill_rate"] == 1.0


def test_normalize_route_keys_preserves_sources() -> None:
    routes = normalize_route_keys(
        {
            "route_business_keys": {
                "freshness": [
                    {
                        "source": "mysql-a",
                        "source_id": "same",
                    },
                ],
                "lexical": [
                    {
                        "source": "mysql-b",
                        "source_id": "same",
                    },
                ],
                "semantic": [],
            }
        }
    )

    assert routes["freshness"] == [
        ("mysql-a", "same")
    ]
    assert routes["lexical"] == [
        ("mysql-b", "same")
    ]


def test_evaluate_and_summarize_allocation() -> None:
    case_result = {
        "case_id": "case-1",
        "query": "测试",
        "relevant_source_ids": [
            "f1",
            "l1",
            "s1",
        ],
        "grade3_source_ids": [
            "s1",
        ],
        "route_business_keys": {
            "freshness": [
                {
                    "source": "mysql",
                    "source_id": "f1",
                },
                {
                    "source": "mysql",
                    "source_id": "f2",
                },
            ],
            "lexical": [
                {
                    "source": "mysql",
                    "source_id": "l1",
                },
                {
                    "source": "mysql",
                    "source_id": "l2",
                },
            ],
            "semantic": [
                {
                    "source": "mysql",
                    "source_id": "s1",
                },
                {
                    "source": "mysql",
                    "source_id": "s2",
                },
            ],
        },
    }

    result = evaluate_case_allocation(
        case_result=case_result,
        allocation={
            "freshness": 2,
            "lexical": 2,
            "semantic": 2,
        },
        total_budget=6,
    )

    assert result["candidate_count"] == 6
    assert result["recall"] == 1.0
    assert result["grade3_hit"] == 1.0

    summary = summarize_allocation(
        [result]
    )

    assert summary["macro_recall"] == 1.0
    assert summary["grade3_hit_rate"] == 1.0
    assert summary[
        "underfilled_case_count"
    ] == 0
