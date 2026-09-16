"""Schemas for geo-aware post search."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

    @model_validator(mode="after")
    def validate_search_parameters(self) -> "PostSearchRequest":
        """Validate relationships between search parameters."""
        self.query = self.query.strip()

        if not self.query:
            raise ValueError("query must not be blank")

        if self.top_k > self.recall_k:
            raise ValueError("top_k cannot exceed recall_k")

        has_latitude = self.latitude is not None
        has_longitude = self.longitude is not None

        if has_latitude != has_longitude:
            raise ValueError(
                "latitude and longitude must be provided together"
            )

        if self.radius_km is not None and not has_latitude:
            raise ValueError(
                "radius_km requires latitude and longitude"
            )

        return self

    model_config = ConfigDict(extra="forbid")


class PostSearchHit(BaseModel):
    """单条帖子搜索结果。"""

    post_id: int
    source: str
    source_id: str

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
    text_score: Optional[float] = None
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
