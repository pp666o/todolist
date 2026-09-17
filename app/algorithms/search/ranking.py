"""Final ranking logic for post search."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, TypedDict


class ScoredSearchCandidate(TypedDict, total=False):
    """Internal candidate representation used during ranking."""

    row: Mapping[str, Any]

    text_score: float
    semantic_score: float | None
    semantic_ranking_score: float

    geo_score: float
    distance_km: float | None

    hot_raw: float
    realtime_hot_raw: float
    unlock_raw: float

    hot_score: float
    unlock_score: float
    final_score: float

    recall_sources: list[str]
    reasons: list[str]


def min_max_normalize(
    values: list[float],
) -> list[float]:
    """Normalize values into the inclusive [0, 1] range."""

    if not values:
        return []

    minimum = min(values)
    maximum = max(values)

    if math.isclose(minimum, maximum):
        return [0.0 for _ in values]

    scale = maximum - minimum

    return [
        (value - minimum) / scale
        for value in values
    ]


def compute_final_scores(
    scored_candidates: list[ScoredSearchCandidate],
    *,
    request_has_geo: bool,
    semantic_weight: float,
) -> None:
    """Combine ranking signals into one final score."""

    static_hot_scores = min_max_normalize(
        [
            candidate["hot_raw"]
            for candidate in scored_candidates
        ]
    )

    realtime_hot_scores = min_max_normalize(
        [
            candidate["realtime_hot_raw"]
            for candidate in scored_candidates
        ]
    )

    unlock_scores = min_max_normalize(
        [
            candidate["unlock_raw"]
            for candidate in scored_candidates
        ]
    )

    has_unlock_signal = any(
        candidate["unlock_raw"] > 0
        for candidate in scored_candidates
    )

    for (
        candidate,
        static_hot_score,
        realtime_hot_score,
        unlock_score,
    ) in zip(
        scored_candidates,
        static_hot_scores,
        realtime_hot_scores,
        unlock_scores,
    ):
        hot_score = (
            0.65 * static_hot_score
            + 0.35 * realtime_hot_score
        )

        weights = {
            "text": 0.50,
            "hot": 0.15,
        }

        if semantic_weight > 0:
            weights["semantic"] = semantic_weight

        if request_has_geo:
            weights["geo"] = 0.25

        if has_unlock_signal:
            weights["unlock"] = 0.10

        weighted_sum = (
            weights["text"]
            * candidate["text_score"]
            + weights["hot"]
            * hot_score
        )

        if "semantic" in weights:
            weighted_sum += (
                weights["semantic"]
                * candidate[
                    "semantic_ranking_score"
                ]
            )

        if "geo" in weights:
            weighted_sum += (
                weights["geo"]
                * candidate["geo_score"]
            )

        if "unlock" in weights:
            weighted_sum += (
                weights["unlock"]
                * unlock_score
            )

        candidate["hot_score"] = hot_score
        candidate["unlock_score"] = unlock_score
        candidate["final_score"] = (
            weighted_sum
            / sum(weights.values())
        )


def sort_and_select_candidates(
    scored_candidates: list[ScoredSearchCandidate],
    *,
    top_k: int,
) -> list[ScoredSearchCandidate]:
    """Sort candidates by ranking priority and keep top-k."""

    scored_candidates.sort(
        key=lambda candidate: (
            -candidate["final_score"],
            -candidate["text_score"],
            -candidate[
                "semantic_ranking_score"
            ],
            (
                candidate["distance_km"]
                if candidate["distance_km"]
                is not None
                else math.inf
            ),
            -int(candidate["row"]["id"]),
        )
    )

    return scored_candidates[:top_k]