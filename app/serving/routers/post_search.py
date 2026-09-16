"""HTTP API for geo-aware post search."""

from fastapi import APIRouter

from todolist.app.features.post_search.post_search import (
    PostSearchRequest,
    PostSearchResponse,
)
from todolist.app.features.post_search.post_search_service import post_search_service


router = APIRouter(
    prefix="/search",
    tags=["post-search"],
)


@router.post(
    "/posts",
    response_model=PostSearchResponse,
    summary="Search geo-aware community posts",
)
async def search_posts(
    request: PostSearchRequest,
) -> PostSearchResponse:
    """Search posts through the post-search application service."""
    return await post_search_service.search(request)
