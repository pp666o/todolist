"""PostgreSQL pgvector semantic retrieval primitives."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Literal, TypedDict

import numpy as np
from psycopg import AsyncConnection

from app.search.embedding import embedding_to_pgvector
from app.algorithms.search.geo import haversine_km


MAX_RECALL_LIMIT = 2000
MAX_EF_SEARCH = 1000
MAX_RADIUS_KM = 500.0
MAX_RADIUS_OVERFETCH_FACTOR = 4.0

IterativeScanMode = Literal[
    "off",
    "strict_order",
]

SUPPORTED_CATEGORIES = {
    "求助",
    "问答",
    "吐槽",
}


class SemanticCandidate(TypedDict):
    """One lightweight semantic recall candidate."""

    source: str
    source_id: str
    semantic_score: float
    semantic_distance: float


def validate_semantic_search_parameters(
    *,
    limit: int,
    ef_search: int,
) -> None:
    """Validate HNSW query parameters before building SQL."""

    if not 1 <= limit <= MAX_RECALL_LIMIT:
        raise ValueError(
            "limit must be between "
            f"1 and {MAX_RECALL_LIMIT}"
        )

    if not 1 <= ef_search <= MAX_EF_SEARCH:
        raise ValueError(
            "ef_search must be between "
            f"1 and {MAX_EF_SEARCH}"
        )


async def semantic_search_global(
    connection: AsyncConnection[dict[str, Any]],
    *,
    query_embedding: Sequence[float] | np.ndarray,
    limit: int,
    ef_search: int,
) -> list[SemanticCandidate]:
    """Recall globally nearest posts through the HNSW index.

    The result intentionally remains lightweight. Full post hydration,
    business filtering, candidate union, deduplication, and ranking are
    handled by later pipeline stages.
    """

    validate_semantic_search_parameters(
        limit=limit,
        ef_search=ef_search,
    )

    query_vector = embedding_to_pgvector(
        query_embedding
    )

    async with connection.transaction():
        async with connection.cursor() as cursor:
            # ef_search is interpolated only after strict integer
            # validation. PostgreSQL SET does not reliably accept a
            # normal query parameter in this position.
            await cursor.execute(
                "SET LOCAL hnsw.ef_search = "
                f"{ef_search}"
            )

            await cursor.execute(
                """
                SELECT
                    source,
                    source_id,
                    (
                        1.0 - (
                            embedding
                            <=> %(query_vector)s::vector
                        )
                    )::double precision
                        AS semantic_score,
                    (
                        embedding
                        <=> %(query_vector)s::vector
                    )::double precision
                        AS semantic_distance
                FROM posts
                WHERE embedding IS NOT NULL
                ORDER BY
                    embedding
                    <=> %(query_vector)s::vector
                LIMIT %(limit)s
                """,
                {
                    "query_vector": query_vector,
                    "limit": limit,
                },
            )

            rows = await cursor.fetchall()

    return [
        SemanticCandidate(
            source=str(row["source"]),
            source_id=str(row["source_id"]),
            semantic_score=float(
                row["semantic_score"]
            ),
            semantic_distance=float(
                row["semantic_distance"]
            ),
        )
        for row in rows
    ]

class FilteredSemanticCandidate(SemanticCandidate):
    """Semantic candidate with geographic fields."""

    latitude: float | None
    longitude: float | None
    distance_km: float | None


def _validate_optional_range(
    *,
    name: str,
    minimum: float | None,
    maximum: float | None,
    lower_bound: float,
    upper_bound: float,
) -> None:
    """Validate one optional inclusive numeric range."""

    if (minimum is None) != (maximum is None):
        raise ValueError(
            f"{name} minimum and maximum "
            "must be provided together"
        )

    if minimum is None or maximum is None:
        return

    if not lower_bound <= minimum <= upper_bound:
        raise ValueError(
            f"{name} minimum must be between "
            f"{lower_bound} and {upper_bound}"
        )

    if not lower_bound <= maximum <= upper_bound:
        raise ValueError(
            f"{name} maximum must be between "
            f"{lower_bound} and {upper_bound}"
        )

    if minimum > maximum:
        raise ValueError(
            f"{name} minimum cannot exceed maximum"
        )


def validate_filtered_semantic_search_parameters(
    *,
    category: str | None,
    min_latitude: float | None,
    max_latitude: float | None,
    min_longitude: float | None,
    max_longitude: float | None,
    latitude: float | None,
    longitude: float | None,
    radius_km: float | None,
    radius_overfetch_factor: float,
    limit: int,
    ef_search: int,
    iterative_scan: IterativeScanMode,
) -> None:
    """Validate filtered semantic retrieval parameters."""

    validate_semantic_search_parameters(
        limit=limit,
        ef_search=ef_search,
    )

    if (
        category is not None
        and category not in SUPPORTED_CATEGORIES
    ):
        raise ValueError(
            f"Unsupported post category: {category!r}"
        )

    _validate_optional_range(
        name="latitude",
        minimum=min_latitude,
        maximum=max_latitude,
        lower_bound=-90.0,
        upper_bound=90.0,
    )
    _validate_optional_range(
        name="longitude",
        minimum=min_longitude,
        maximum=max_longitude,
        lower_bound=-180.0,
        upper_bound=180.0,
    )

    has_latitude = latitude is not None
    has_longitude = longitude is not None

    if has_latitude != has_longitude:
        raise ValueError(
            "latitude and longitude must be "
            "provided together"
        )

    if latitude is not None:
        if not -90.0 <= latitude <= 90.0:
            raise ValueError(
                "latitude must be between -90 and 90"
            )

    if longitude is not None:
        if not -180.0 <= longitude <= 180.0:
            raise ValueError(
                "longitude must be between -180 and 180"
            )

    if radius_km is not None:
        if not has_latitude:
            raise ValueError(
                "radius_km requires latitude "
                "and longitude"
            )

        if not 0.0 < radius_km <= MAX_RADIUS_KM:
            raise ValueError(
                "radius_km must be greater than zero "
                f"and no more than {MAX_RADIUS_KM}"
            )

    if not (
        1.0
        <= radius_overfetch_factor
        <= MAX_RADIUS_OVERFETCH_FACTOR
    ):
        raise ValueError(
            "radius_overfetch_factor must be between "
            f"1 and {MAX_RADIUS_OVERFETCH_FACTOR}"
        )

    if iterative_scan not in {
        "off",
        "strict_order",
    }:
        raise ValueError(
            "iterative_scan must be one of: "
            "off, strict_order"
        )


async def semantic_search_filtered(
    connection: AsyncConnection[dict[str, Any]],
    *,
    query_embedding: Sequence[float] | np.ndarray,
    category: str | None = None,
    visible_statuses: Sequence[str] | None = None,
    city: str | None = None,
    district: str | None = None,
    min_latitude: float | None = None,
    max_latitude: float | None = None,
    min_longitude: float | None = None,
    max_longitude: float | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    radius_overfetch_factor: float = 1.5,
    limit: int,
    ef_search: int,
    iterative_scan: IterativeScanMode = "off",
) -> list[FilteredSemanticCandidate]:
    """Recall semantically nearest posts under business filters.

    SQL applies deterministic business filters and the coarse
    geographic bounding box. Exact radius filtering reuses the same
    Python Haversine implementation as the online search service.

    When exact radius filtering is active, the SQL query over-fetches
    candidates before the final Python radius check. The function may
    still return fewer than ``limit`` candidates; callers must treat
    the returned count as an observable recall signal.
    """

    validate_filtered_semantic_search_parameters(
        category=category,
        min_latitude=min_latitude,
        max_latitude=max_latitude,
        min_longitude=min_longitude,
        max_longitude=max_longitude,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        radius_overfetch_factor=(
            radius_overfetch_factor
        ),
        limit=limit,
        ef_search=ef_search,
        iterative_scan=iterative_scan,
    )

    normalized_statuses = list(
        dict.fromkeys(
            status.strip()
            for status in (
                visible_statuses or ()
            )
            if status and status.strip()
        )
    )

    normalized_city = (
        city.strip()
        if city and city.strip()
        else None
    )
    normalized_district = (
        district.strip()
        if district and district.strip()
        else None
    )

    conditions = [
        "embedding IS NOT NULL",
    ]

    query_vector = embedding_to_pgvector(
        query_embedding
    )

    scan_limit = limit

    if radius_km is not None:
        scan_limit = min(
            MAX_RECALL_LIMIT,
            max(
                limit,
                math.ceil(
                    limit
                    * radius_overfetch_factor
                ),
            ),
        )

    parameters: dict[str, Any] = {
        "query_vector": query_vector,
        "scan_limit": scan_limit,
    }

    if category is not None:
        conditions.append(
            "category = %(category)s"
        )
        parameters["category"] = category

    if normalized_statuses:
        conditions.append(
            "visible_status = "
            "ANY(%(visible_statuses)s)"
        )
        parameters[
            "visible_statuses"
        ] = normalized_statuses

    if normalized_city:
        conditions.append(
            "city = %(city)s"
        )
        parameters["city"] = normalized_city

    if normalized_district:
        conditions.append(
            "district = %(district)s"
        )
        parameters[
            "district"
        ] = normalized_district

    if (
        min_latitude is not None
        and max_latitude is not None
    ):
        conditions.append(
            "latitude BETWEEN "
            "%(min_latitude)s "
            "AND %(max_latitude)s"
        )
        parameters[
            "min_latitude"
        ] = min_latitude
        parameters[
            "max_latitude"
        ] = max_latitude

    if (
        min_longitude is not None
        and max_longitude is not None
    ):
        conditions.append(
            "longitude BETWEEN "
            "%(min_longitude)s "
            "AND %(max_longitude)s"
        )
        parameters[
            "min_longitude"
        ] = min_longitude
        parameters[
            "max_longitude"
        ] = max_longitude

    where_sql = (
        "\n                    AND ".join(
            conditions
        )
    )

    async with connection.transaction():
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SET LOCAL hnsw.ef_search = "
                f"{ef_search}"
            )

            await cursor.execute(
                "SET LOCAL hnsw.iterative_scan = "
                f"{iterative_scan}"
            )

            await cursor.execute(
                f"""
                SELECT
                    source,
                    source_id,
                    latitude,
                    longitude,
                    (
                        1.0 - (
                            embedding
                            <=> %(query_vector)s::vector
                        )
                    )::double precision
                        AS semantic_score,
                    (
                        embedding
                        <=> %(query_vector)s::vector
                    )::double precision
                        AS semantic_distance
                FROM posts
                WHERE
                    {where_sql}
                ORDER BY
                    embedding
                    <=> %(query_vector)s::vector
                LIMIT %(scan_limit)s
                """,
                parameters,
            )

            rows = await cursor.fetchall()

    candidates: list[
        FilteredSemanticCandidate
    ] = []

    for row in rows:
        row_latitude = (
            float(row["latitude"])
            if row["latitude"] is not None
            else None
        )
        row_longitude = (
            float(row["longitude"])
            if row["longitude"] is not None
            else None
        )

        distance_km: float | None = None

        if radius_km is not None:
            if (
                row_latitude is None
                or row_longitude is None
                or latitude is None
                or longitude is None
            ):
                continue

            distance_km = haversine_km(
                latitude,
                longitude,
                row_latitude,
                row_longitude,
            )

            if distance_km > radius_km:
                continue

        candidates.append(
            FilteredSemanticCandidate(
                source=str(row["source"]),
                source_id=str(
                    row["source_id"]
                ),
                semantic_score=float(
                    row["semantic_score"]
                ),
                semantic_distance=float(
                    row["semantic_distance"]
                ),
                latitude=row_latitude,
                longitude=row_longitude,
                distance_km=distance_km,
            )
        )

        if len(candidates) >= limit:
            break

    return candidates

