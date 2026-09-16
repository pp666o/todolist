"""Popularity and engagement signals for search ranking."""

import math
from collections.abc import Mapping
from typing import Any


def calculate_static_hot_raw(
    row: Mapping[str, Any],
) -> float:
    """Calculate long-term popularity from persisted post counters."""

    views = max(0, int(row.get("views") or 0))
    likes = max(0, int(row.get("likes") or 0))
    marks = max(0, int(row.get("marks") or 0))
    dislikes = max(0, int(row.get("dislikes") or 0))

    return max(
        0.0,
        0.20 * math.log1p(views)
        + 0.40 * math.log1p(likes)
        + 0.30 * math.log1p(marks)
        - 0.10 * math.log1p(dislikes),
    )


def calculate_realtime_hot_raw(
    features: Mapping[str, Any],
) -> float:
    """Calculate short-term popularity from realtime counters."""

    views_1h = max(
        0,
        int(features.get("views_1h", 0)),
    )
    views_24h = max(
        0,
        int(features.get("views_24h", 0)),
    )
    likes_24h = max(
        0,
        int(features.get("likes_24h", 0)),
    )
    marks_24h = max(
        0,
        int(features.get("marks_24h", 0)),
    )

    return (
        0.20 * math.log1p(views_1h)
        + 0.25 * math.log1p(views_24h)
        + 0.35 * math.log1p(likes_24h)
        + 0.20 * math.log1p(marks_24h)
    )


def calculate_unlock_signal_raw(
    features: Mapping[str, Any],
) -> float:
    """Calculate recent unlock engagement signal."""

    unlocks_24h = max(
        0,
        int(features.get("unlocks_24h", 0)),
    )

    return math.log1p(unlocks_24h)