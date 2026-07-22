"""PostgreSQL pgvector semantic retrieval primitives."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypedDict

import numpy as np
from psycopg import AsyncConnection

from app.search.embedding import embedding_to_pgvector


MAX_RECALL_LIMIT = 2000
MAX_EF_SEARCH = 10000


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
