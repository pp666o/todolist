"""Schemas for geo-aware post search."""

from typing import Optional

from pydantic import BaseModel, Field

from app.domain.post import PostCategory


class PostSearchRequest(BaseModel):
    """帖子搜索请求。"""

    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="用户输入的自然语言搜索词",
    )
    user_id: Optional[str] = Field(
        default=None,
        description="可选用户标识，用于后续个性化排序",
    )

    top_k: int = Field(default=10, ge=1, le=100)
    recall_k: int = Field(default=200, ge=1, le=2000)

    category: Optional[PostCategory] = None
    visible_statuses: list[str] = Field(default_factory=list)

    city: Optional[str] = Field(default=None, max_length=100)
    district: Optional[str] = Field(default=None, max_length=100)

    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_km: Optional[float] = Field(default=None, gt=0, le=500)

    class Config:
        extra = "forbid"


class PostSearchHit(BaseModel):
    """单条帖子搜索结果。"""

    post_id: int
    title: str
    content: str
    category: PostCategory
    tags: list[str] = Field(default_factory=list)

    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None

    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_km: Optional[float] = None

    score: float
    semantic_score: Optional[float] = None
    bm25_score: Optional[float] = None
    geo_score: Optional[float] = None
    hot_score: Optional[float] = None
    unlock_score: Optional[float] = None

    recall_sources: list[str] = Field(default_factory=list)
    reason: Optional[str] = None


class PostSearchResponse(BaseModel):
    """帖子搜索响应。"""

    request_id: str
    query: str
    total_candidates: int = Field(ge=0)
    result_count: int = Field(ge=0)
    items: list[PostSearchHit] = Field(default_factory=list)

    degraded: bool = False
    degraded_reason: Optional[str] = None
