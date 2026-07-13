from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from .database import Base


class Todo(Base):
    __tablename__ = "todos"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_todos_source_source_id"),
        Index("ix_todos_category", "category"),
        Index("ix_todos_city", "city"),
    )

    id = Column(Integer, primary_key=True, index=True)

    # Searchable text shown by the existing client.
    content = Column(Text, nullable=False)
    title = Column(String(255))
    detail = Column(Text)

    # Import provenance. source_id remains nullable for manually-created todos.
    source = Column(String(64), nullable=False, default="manual", server_default="manual")
    source_id = Column(String(128))
    user_id = Column(BigInteger, index=True)

    category = Column(String(32))
    tags = Column(Text)

    latitude = Column(Float)
    longitude = Column(Float)
    country = Column(String(64))
    province = Column(String(64))
    city = Column(String(64))
    district = Column(String(64))
    address = Column(String(128))

    like_count = Column(Integer)
    view_count = Column(Integer)
    mark_count = Column(Integer)
    dislike_count = Column(Integer)
    rate_score = Column(Float)
    visible_status = Column(Integer)

    # paraphrase-multilingual-MiniLM-L12-v2 returns 384 dimensions.
    embedding = Column(Vector(384))

    start_time = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True))


class Interaction(Base):
    """User actions used by the lightweight prediction baselines."""

    __tablename__ = "interactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    todo_id = Column(Integer, ForeignKey("todos.id"), index=True)
    action_type = Column(String(50))
    day_of_week = Column(Integer)
    hour_of_day = Column(Integer)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    todo = relationship("Todo")
