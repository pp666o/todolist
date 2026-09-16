"""Online semantic-recall runtime with process-level model caching."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

from app.infrastructure.postgres import connect_postgres
from app.features.post_search.post_search import PostSearchRequest
from app.search.embedding import (
    DEFAULT_MODEL_PATH,
    encode_query,
    load_model,
    resolve_device,
)
from app.algorithms.search.geo import calculate_bounding_box
from app.search.semantic_retrieval import (
    FilteredSemanticCandidate,
    semantic_search_filtered,
)


DEFAULT_SEMANTIC_LIMIT = 200
DEFAULT_SEMANTIC_EF_SEARCH = 200
DEFAULT_SEMANTIC_ITERATIVE_SCAN = "strict_order"
DEFAULT_RADIUS_OVERFETCH_FACTOR = 2.0


@lru_cache(maxsize=1)
def get_semantic_model() -> Any:
    """Load the local BGE model once per application process."""

    device = resolve_device("auto")

    return load_model(
        DEFAULT_MODEL_PATH,
        device=device,
    )


def _category_value(
    request: PostSearchRequest,
) -> str | None:
    """Return the plain category value expected by PostgreSQL."""

    if request.category is None:
        return None

    value = getattr(
        request.category,
        "value",
        request.category,
    )

    return str(value)


async def recall_filtered_semantic(
    request: PostSearchRequest,
) -> list[FilteredSemanticCandidate]:
    """Encode one query and run filtered pgvector HNSW recall."""

    model = await asyncio.to_thread(
        get_semantic_model
    )
    query_embedding = await asyncio.to_thread(
        encode_query,
        model,
        request.query,
    )

    bounding_box: dict[str, float | None] = {
        "min_latitude": None,
        "max_latitude": None,
        "min_longitude": None,
        "max_longitude": None,
    }

    if (
        request.latitude is not None
        and request.longitude is not None
        and request.radius_km is not None
    ):
        bounding_box = calculate_bounding_box(
            request.latitude,
            request.longitude,
            request.radius_km,
        )

    limit = min(
        request.recall_k,
        DEFAULT_SEMANTIC_LIMIT,
    )

    async with await connect_postgres() as connection:
        return await semantic_search_filtered(
            connection,
            query_embedding=query_embedding,
            category=_category_value(request),
            visible_statuses=request.visible_statuses,
            city=request.city,
            district=request.district,
            min_latitude=bounding_box[
                "min_latitude"
            ],
            max_latitude=bounding_box[
                "max_latitude"
            ],
            min_longitude=bounding_box[
                "min_longitude"
            ],
            max_longitude=bounding_box[
                "max_longitude"
            ],
            latitude=request.latitude,
            longitude=request.longitude,
            radius_km=request.radius_km,
            radius_overfetch_factor=(
                DEFAULT_RADIUS_OVERFETCH_FACTOR
            ),
            limit=limit,
            ef_search=DEFAULT_SEMANTIC_EF_SEARCH,
            iterative_scan=(
                DEFAULT_SEMANTIC_ITERATIVE_SCAN
            ),
        )
