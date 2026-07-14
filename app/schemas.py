from datetime import datetime

from pydantic import BaseModel, Field


class TodoCreate(BaseModel):
    content: str
    start_time: datetime | None = None


class SearchRequest(BaseModel):
    query: str
    start_time: datetime | str | None = None
    end_time: datetime | str | None = None
    top_k: int = 5


class TodoResponse(BaseModel):
    id: int
    content: str
    title: str | None = None
    category: str | None = None
    tags: str | None = None
    city: str | None = None
    district: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    source: str | None = None
    source_id: str | None = None

    created_at: datetime | None = None
    start_time: datetime | str | None = None

    is_ad: bool = False
    ad_payload: str | None = None

    class Config:
        from_attributes = True


class PostSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)

    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float | None = Field(default=None, gt=0, le=500)

    city: str | None = None
    district: str | None = None
    category: str | None = None
    visible_statuses: list[int] | None = None

    top_k: int = Field(default=10, ge=1, le=50)
    recall_k: int = Field(default=100, ge=10, le=1000)


class PostSearchItem(BaseModel):
    id: int
    source_id: str | None = None
    title: str | None = None
    content: str
    category: str | None = None
    tags: str | None = None

    city: str | None = None
    district: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    visible_status: int | None = None

    semantic_score: float
    distance_km: float | None = None
    popularity_score: float
    final_score: float

    recall_sources: list[str]
    reason: str
    created_at: datetime | None = None


class PostSearchResponse(BaseModel):
    request_id: str
    query: str
    dense_candidate_count: int
    filtered_candidate_count: int
    results: list[PostSearchItem]


class PredictRequest(BaseModel):
    content: str
    start_time: str | None = None


class AuditRequest(BaseModel):
    raw_payload: str
    action: str
