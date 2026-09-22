"""Dependency assembly for the HTTP serving layer."""

from functools import lru_cache

from app.features.post_search.post_search_service import (
    PostSearchService,
)
from app.infrastructure.redis import (
    get_post_realtime_features,
)
from app.repositories.post_repository import (
    post_repository,
)


@lru_cache
def get_post_search_service() -> PostSearchService:
    """Return the production post-search service."""

    return PostSearchService(
        repository=post_repository,
        realtime_feature_loader=(
            get_post_realtime_features
        ),
    )