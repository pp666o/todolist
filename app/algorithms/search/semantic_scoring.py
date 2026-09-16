"""Semantic score calibration for post search."""

import math


def calibrate_semantic_score(
    semantic_score: float | None,
    *,
    minimum_score: float,
) -> float:
    """Calibrate a raw semantic similarity into a [0, 1] ranking signal."""

    if semantic_score is None:
        return 0.0

    normalized_score = min(
        1.0,
        max(
            0.0,
            float(semantic_score),
        ),
    )

    if normalized_score < minimum_score:
        return 0.0

    if math.isclose(
        minimum_score,
        1.0,
    ):
        return (
            1.0
            if math.isclose(
                normalized_score,
                1.0,
            )
            else 0.0
        )

    return min(
        1.0,
        max(
            0.0,
            (
                normalized_score
                - minimum_score
            )
            / (
                1.0
                - minimum_score
            ),
        ),
    )