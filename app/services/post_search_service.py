"""Application service for geo-aware post search."""

from app.schemas.post_search import PostSearchRequest, PostSearchResponse


class PostSearchNotReadyError(RuntimeError):
    """Raised when the post-search infrastructure has not been connected."""


class PostSearchService:
    """Coordinate recall, filtering, ranking, and result assembly."""

    async def search(self, request: PostSearchRequest) -> PostSearchResponse:
        """Search posts using the configured recall and ranking backends."""
        raise PostSearchNotReadyError(
            "Post search is not ready: PostgreSQL and recall backends are not connected."
        )


post_search_service = PostSearchService()
