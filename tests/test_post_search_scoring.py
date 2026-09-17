"""Unit tests for post-search scoring helpers."""

import math

from app.algorithms.search.ranking import (
    min_max_normalize,
)
from app.features.post_search.post_search_service import (
    _calculate_bounding_box,
    _character_bigrams,
    _field_match_score,
    _haversine_km,
    _normalize_text,
    _realtime_hot_raw,
    _static_hot_raw,
    _unlock_raw,
)


def test_normalize_text() -> None:
    assert _normalize_text("  ＡＢＣ   测试  ") == "abc 测试"
    assert _normalize_text(None) == ""


def test_character_bigrams() -> None:
    assert _character_bigrams("附近修电脑") == {
        "附近",
        "近修",
        "修电",
        "电脑",
    }

    assert _character_bigrams("电") == {"电"}
    assert _character_bigrams("") == set()


def test_field_match_score_prioritizes_exact_match() -> None:
    exact = _field_match_score("修电脑", "修电脑")
    substring = _field_match_score(
        "修电脑",
        "附近可以修电脑",
    )
    unrelated = _field_match_score(
        "修电脑",
        "今天去公园散步",
    )

    assert exact == 1.0
    assert 0 < substring < exact
    assert unrelated == 0.0


def test_haversine_same_location_is_zero() -> None:
    distance = _haversine_km(
        37.689434,
        112.761673,
        37.689434,
        112.761673,
    )

    assert math.isclose(distance, 0.0, abs_tol=1e-9)


def test_bounding_box_contains_center() -> None:
    box = _calculate_bounding_box(
        latitude=37.689434,
        longitude=112.761673,
        radius_km=10.0,
    )

    assert box["min_latitude"] < 37.689434
    assert box["max_latitude"] > 37.689434
    assert box["min_longitude"] < 112.761673
    assert box["max_longitude"] > 112.761673


def test_min_max_normalization() -> None:
    assert min_max_normalize([10.0, 20.0, 30.0]) == [
        0.0,
        0.5,
        1.0,
    ]

    assert min_max_normalize([5.0]) == [0.0]
    assert min_max_normalize([5.0, 5.0]) == [0.0, 0.0]
    assert min_max_normalize([]) == []


def test_hot_and_unlock_scores_are_nonnegative() -> None:
    row = {
        "views": 100,
        "likes": 20,
        "marks": 5,
        "dislikes": 2,
    }

    realtime = {
        "views_1h": 10,
        "views_24h": 100,
        "likes_24h": 20,
        "marks_24h": 5,
        "unlocks_24h": 3,
    }

    assert _static_hot_raw(row) > 0
    assert _realtime_hot_raw(realtime) > 0
    assert _unlock_raw(realtime) > 0
