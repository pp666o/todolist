"""Domain models for community posts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PostCategory = Literal["求助", "问答", "吐槽"]


class PostUpsert(BaseModel):
    """Canonical post data accepted by the PostgreSQL repository."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    source: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1)

    title: str = Field(min_length=1)
    content: str = ""
    category: PostCategory
    tags: list[str] = Field(default_factory=list)

    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    country: str | None = Field(default=None, max_length=100)
    province: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    address: str | None = None

    likes: int = Field(default=0, ge=0)
    views: int = Field(default=0, ge=0)
    marks: int = Field(default=0, ge=0)
    dislikes: int = Field(default=0, ge=0)
    ratescore: float | None = None
    visible_status: str | None = Field(default=None, max_length=32)
    owner_id: str | None = None

    created_at: datetime | None = None
    updated_at: datetime | None = None
