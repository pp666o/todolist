from datetime import datetime

from pydantic import BaseModel


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


class PredictRequest(BaseModel):
    content: str
    start_time: str | None = None


class AuditRequest(BaseModel):
    raw_payload: str
    action: str
