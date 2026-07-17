"""HTTP API for geo-aware post search."""

from fastapi import APIRouter, HTTPException, status

from app.schemas.post_search import PostSearchRequest, PostSearchResponse
from app.services.post_search_service import (
    PostSearchNotReadyError,
    post_search_service,
)

router = APIRouter(prefix="/search", tags=["post-search"])


@router.post(
    "/posts",
    response_model=PostSearchResponse,
    summary="Search geo-aware community posts",
)
async def search_posts(request: PostSearchRequest) -> PostSearchResponse:
    """Search posts through the post-search application service."""
    try:
        return await post_search_service.search(request)
    except PostSearchNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
