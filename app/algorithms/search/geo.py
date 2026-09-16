"""Shared geographic calculations for search and retrieval."""

from __future__ import annotations

import math


EARTH_RADIUS_KM = 6371.0088


def haversine_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Calculate great-circle distance in kilometres."""

    latitude_a_rad = math.radians(latitude_a)
    latitude_b_rad = math.radians(latitude_b)

    latitude_delta = math.radians(
        latitude_b - latitude_a
    )
    longitude_delta = math.radians(
        longitude_b - longitude_a
    )

    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(latitude_a_rad)
        * math.cos(latitude_b_rad)
        * math.sin(longitude_delta / 2) ** 2
    )

    angular_distance = 2 * math.asin(
        min(1.0, math.sqrt(haversine))
    )

    return EARTH_RADIUS_KM * angular_distance


def calculate_bounding_box(
    latitude: float,
    longitude: float,
    radius_km: float,
) -> dict[str, float | None]:
    """Calculate a coarse SQL latitude/longitude bounding box."""

    if not -90.0 <= latitude <= 90.0:
        raise ValueError(
            "latitude must be between -90 and 90"
        )

    if not -180.0 <= longitude <= 180.0:
        raise ValueError(
            "longitude must be between -180 and 180"
        )

    if radius_km <= 0:
        raise ValueError(
            "radius_km must be greater than zero"
        )

    latitude_delta = radius_km / 111.32

    min_latitude = max(
        -90.0,
        latitude - latitude_delta,
    )
    max_latitude = min(
        90.0,
        latitude + latitude_delta,
    )

    cosine = abs(
        math.cos(
            math.radians(latitude)
        )
    )

    if cosine < 1e-6:
        return {
            "min_latitude": min_latitude,
            "max_latitude": max_latitude,
            "min_longitude": None,
            "max_longitude": None,
        }

    longitude_delta = (
        radius_km
        / (111.32 * cosine)
    )

    # Do not express date-line-crossing boxes as one BETWEEN
    # interval. Exact Haversine filtering remains authoritative.
    if (
        longitude - longitude_delta < -180.0
        or longitude + longitude_delta > 180.0
    ):
        min_longitude = None
        max_longitude = None
    else:
        min_longitude = (
            longitude - longitude_delta
        )
        max_longitude = (
            longitude + longitude_delta
        )

    return {
        "min_latitude": min_latitude,
        "max_latitude": max_latitude,
        "min_longitude": min_longitude,
        "max_longitude": max_longitude,
    }
