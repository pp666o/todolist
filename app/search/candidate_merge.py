"""Candidate union, deduplication, and hydration helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypedDict


FRESHNESS_RECALL_SOURCE = "freshness"
SEMANTIC_RECALL_SOURCE = "semantic"


class MergedRecallCandidate(TypedDict):
    """One lightweight candidate produced by multi-route recall."""

    source: str
    source_id: str
    freshness_rank: int | None
    semantic_rank: int | None
    semantic_score: float | None
    semantic_distance: float | None
    recall_sources: list[str]


class HydratedRecallCandidate(MergedRecallCandidate):
    """Merged candidate with its complete PostgreSQL post row."""

    row: dict[str, Any]


def candidate_key(
    candidate: Mapping[str, Any],
) -> tuple[str, str]:
    """Return and validate the business-unique candidate key."""

    source = str(
        candidate.get("source") or ""
    ).strip()
    source_id = str(
        candidate.get("source_id") or ""
    ).strip()

    if not source:
        raise ValueError(
            "candidate source must not be blank"
        )

    if not source_id:
        raise ValueError(
            "candidate source_id must not be blank"
        )

    return source, source_id


def _append_recall_source(
    candidate: MergedRecallCandidate,
    recall_source: str,
) -> None:
    """Append one recall source without creating duplicates."""

    if recall_source not in candidate["recall_sources"]:
        candidate["recall_sources"].append(
            recall_source
        )


def merge_recall_candidates(
    *,
    freshness_candidates: Sequence[
        Mapping[str, Any]
    ],
    semantic_candidates: Sequence[
        Mapping[str, Any]
    ],
) -> list[MergedRecallCandidate]:
    """Union Freshness and Semantic candidates by business key.

    Candidate order is deterministic:

    1. Freshness candidates keep their original order.
    2. Semantic-only candidates follow in semantic rank order.
    3. Posts recalled by both routes remain at their Freshness
       position and receive both recall-source markers.
    """

    merged_by_key: dict[
        tuple[str, str],
        MergedRecallCandidate,
    ] = {}
    ordered_keys: list[tuple[str, str]] = []

    for rank, candidate in enumerate(
        freshness_candidates,
        start=1,
    ):
        source, source_id = candidate_key(
            candidate
        )
        key = source, source_id

        merged = merged_by_key.get(key)

        if merged is None:
            merged = MergedRecallCandidate(
                source=source,
                source_id=source_id,
                freshness_rank=rank,
                semantic_rank=None,
                semantic_score=None,
                semantic_distance=None,
                recall_sources=[],
            )
            merged_by_key[key] = merged
            ordered_keys.append(key)

        if merged["freshness_rank"] is None:
            merged["freshness_rank"] = rank

        _append_recall_source(
            merged,
            FRESHNESS_RECALL_SOURCE,
        )

    for rank, candidate in enumerate(
        semantic_candidates,
        start=1,
    ):
        source, source_id = candidate_key(
            candidate
        )
        key = source, source_id

        merged = merged_by_key.get(key)

        if merged is None:
            merged = MergedRecallCandidate(
                source=source,
                source_id=source_id,
                freshness_rank=None,
                semantic_rank=rank,
                semantic_score=None,
                semantic_distance=None,
                recall_sources=[],
            )
            merged_by_key[key] = merged
            ordered_keys.append(key)

        if merged["semantic_rank"] is None:
            merged["semantic_rank"] = rank

        semantic_score = candidate.get(
            "semantic_score"
        )

        if semantic_score is not None:
            normalized_score = float(
                semantic_score
            )

            if (
                merged["semantic_score"] is None
                or normalized_score
                > merged["semantic_score"]
            ):
                merged["semantic_score"] = (
                    normalized_score
                )

                semantic_distance = candidate.get(
                    "semantic_distance"
                )
                merged["semantic_distance"] = (
                    float(semantic_distance)
                    if semantic_distance is not None
                    else None
                )

        _append_recall_source(
            merged,
            SEMANTIC_RECALL_SOURCE,
        )

    return [
        merged_by_key[key]
        for key in ordered_keys
    ]


def hydrate_recall_candidates(
    candidates: Sequence[MergedRecallCandidate],
    rows: Sequence[dict[str, Any]],
) -> list[HydratedRecallCandidate]:
    """Attach complete post rows while preserving recall order.

    Missing database rows are skipped because a post may be deleted
    between recall and hydration.
    """

    row_by_key = {
        candidate_key(row): row
        for row in rows
    }

    hydrated: list[
        HydratedRecallCandidate
    ] = []

    for candidate in candidates:
        key = (
            candidate["source"],
            candidate["source_id"],
        )
        row = row_by_key.get(key)

        if row is None:
            continue

        hydrated.append(
            HydratedRecallCandidate(
                **candidate,
                row=row,
            )
        )

    return hydrated
