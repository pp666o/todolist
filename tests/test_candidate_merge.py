"""Tests for multi-route post candidate merging."""

from __future__ import annotations

import pytest

from todolist.app.algorithms.search.candidate_merge import (
    hydrate_recall_candidates,
    merge_recall_candidates,
)


def test_merge_preserves_freshness_then_semantic_order() -> None:
    merged = merge_recall_candidates(
        freshness_candidates=[
            {
                "source": "mysql",
                "source_id": "fresh-1",
            },
            {
                "source": "mysql",
                "source_id": "shared",
            },
        ],
        semantic_candidates=[
            {
                "source": "mysql",
                "source_id": "shared",
                "semantic_score": 0.9,
                "semantic_distance": 0.1,
            },
            {
                "source": "mysql",
                "source_id": "semantic-1",
                "semantic_score": 0.8,
                "semantic_distance": 0.2,
            },
        ],
    )

    assert [
        candidate["source_id"]
        for candidate in merged
    ] == [
        "fresh-1",
        "shared",
        "semantic-1",
    ]

    assert merged[0] == {
        "source": "mysql",
        "source_id": "fresh-1",
        "freshness_rank": 1,
        "semantic_rank": None,
        "semantic_score": None,
        "semantic_distance": None,
        "recall_sources": ["freshness"],
    }

    assert merged[1] == {
        "source": "mysql",
        "source_id": "shared",
        "freshness_rank": 2,
        "semantic_rank": 1,
        "semantic_score": 0.9,
        "semantic_distance": 0.1,
        "recall_sources": [
            "freshness",
            "semantic",
        ],
    }

    assert merged[2]["freshness_rank"] is None
    assert merged[2]["semantic_rank"] == 2
    assert merged[2]["recall_sources"] == [
        "semantic"
    ]


def test_merge_uses_source_and_source_id_as_key() -> None:
    merged = merge_recall_candidates(
        freshness_candidates=[
            {
                "source": "mysql-a",
                "source_id": "42",
            },
        ],
        semantic_candidates=[
            {
                "source": "mysql-b",
                "source_id": "42",
                "semantic_score": 0.7,
                "semantic_distance": 0.3,
            },
        ],
    )

    assert len(merged) == 2
    assert [
        (
            candidate["source"],
            candidate["source_id"],
        )
        for candidate in merged
    ] == [
        ("mysql-a", "42"),
        ("mysql-b", "42"),
    ]


def test_merge_deduplicates_repeated_route_candidates() -> None:
    merged = merge_recall_candidates(
        freshness_candidates=[
            {
                "source": "mysql",
                "source_id": "same",
            },
            {
                "source": "mysql",
                "source_id": "same",
            },
        ],
        semantic_candidates=[
            {
                "source": "mysql",
                "source_id": "same",
                "semantic_score": 0.6,
                "semantic_distance": 0.4,
            },
            {
                "source": "mysql",
                "source_id": "same",
                "semantic_score": 0.8,
                "semantic_distance": 0.2,
            },
        ],
    )

    assert len(merged) == 1
    assert merged[0]["freshness_rank"] == 1
    assert merged[0]["semantic_rank"] == 1
    assert merged[0]["semantic_score"] == 0.8
    assert merged[0]["semantic_distance"] == 0.2
    assert merged[0]["recall_sources"] == [
        "freshness",
        "semantic",
    ]


def test_hydrate_preserves_merged_order_and_skips_missing() -> None:
    merged = merge_recall_candidates(
        freshness_candidates=[
            {
                "source": "mysql",
                "source_id": "a",
            },
        ],
        semantic_candidates=[
            {
                "source": "mysql",
                "source_id": "missing",
                "semantic_score": 0.8,
                "semantic_distance": 0.2,
            },
            {
                "source": "mysql",
                "source_id": "b",
                "semantic_score": 0.7,
                "semantic_distance": 0.3,
            },
        ],
    )

    hydrated = hydrate_recall_candidates(
        merged,
        [
            {
                "id": 2,
                "source": "mysql",
                "source_id": "b",
                "title": "B",
            },
            {
                "id": 1,
                "source": "mysql",
                "source_id": "a",
                "title": "A",
            },
        ],
    )

    assert [
        candidate["source_id"]
        for candidate in hydrated
    ] == [
        "a",
        "b",
    ]
    assert hydrated[0]["row"]["title"] == "A"
    assert hydrated[1]["row"]["title"] == "B"


@pytest.mark.parametrize(
    "candidate",
    [
        {
            "source": "",
            "source_id": "1",
        },
        {
            "source": "mysql",
            "source_id": "",
        },
    ],
)
def test_merge_rejects_blank_business_keys(
    candidate: dict[str, str],
) -> None:
    with pytest.raises(
        ValueError,
        match="must not be blank",
    ):
        merge_recall_candidates(
            freshness_candidates=[
                candidate
            ],
            semantic_candidates=[],
        )
