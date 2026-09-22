"""HTTP API for geo-aware post search."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.features.post_search.post_search import (
    PostSearchRequest,
    PostSearchResponse,
)
from app.features.post_search.post_search_service import (
    PostSearchService,
)
from app.serving.dependencies import (
    get_post_search_service,
)


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
    service: Annotated[
        PostSearchService,
        Depends(get_post_search_service),
    ],
) -> PostSearchResponse:
    """Search posts through the post-search application service."""

    return await service.search(request)
