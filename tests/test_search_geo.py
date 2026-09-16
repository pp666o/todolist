from __future__ import annotations

import pytest

from app.algorithms.search.geo import (
    EARTH_RADIUS_KM,
    calculate_bounding_box,
    haversine_km,
)


def test_earth_radius_uses_mean_radius() -> None:
    assert EARTH_RADIUS_KM == 6371.0088


def test_haversine_same_point_is_zero() -> None:
    assert haversine_km(
        37.0,
        112.0,
        37.0,
        112.0,
    ) == pytest.approx(0.0)


def test_haversine_one_degree_latitude() -> None:
    assert haversine_km(
        0.0,
        0.0,
        1.0,
        0.0,
    ) == pytest.approx(
        111.195,
        abs=0.01,
    )


def test_bounding_box_contains_center() -> None:
    box = calculate_bounding_box(
        37.689434,
        112.761673,
        10.0,
    )

    assert (
        box["min_latitude"]
        < 37.689434
        < box["max_latitude"]
    )
    assert (
        box["min_longitude"]
        is not None
    )
    assert (
        box["max_longitude"]
        is not None
    )
    assert (
        box["min_longitude"]
        < 112.761673
        < box["max_longitude"]
    )


def test_bounding_box_skips_date_line_interval() -> None:
    box = calculate_bounding_box(
        0.0,
        179.99,
        10.0,
    )

    assert box["min_longitude"] is None
    assert box["max_longitude"] is None


@pytest.mark.parametrize(
    ("latitude", "longitude", "radius_km", "message"),
    [
        (91.0, 0.0, 10.0, "latitude"),
        (0.0, 181.0, 10.0, "longitude"),
        (0.0, 0.0, 0.0, "radius_km"),
        (0.0, 0.0, -1.0, "radius_km"),
    ],
)
def test_bounding_box_rejects_invalid_input(
    latitude: float,
    longitude: float,
    radius_km: float,
    message: str,
) -> None:
    with pytest.raises(
        ValueError,
        match=message,
    ):
        calculate_bounding_box(
            latitude,
            longitude,
            radius_km,
        )
