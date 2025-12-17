from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from .database import Base

class Todo(Base):
    __tablename__ = "todos"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    
    # Core: store 384-dim vector
    embedding = Column(Vector(384))
    
    start_time = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Interaction(Base):
    """
    目标二核心表：记录用户行为，用于机器学习训练
    """
    __tablename__ = "interactions"

    id = Column(Integer, primary_key=True, index=True)
    
    #User ID (暂不关联 User 表)
    user_id = Column(Integer, index=True)
    
    #related task ID
    todo_id = Column(Integer, ForeignKey("todos.id"))
    
    # modification class: "complete", "view", "reject"
    action_type = Column(String(50))
    
    # key!! complicated features for ML
    day_of_week = Column(Integer) # 0=周一, 6=周日
    hour_of_day = Column(Integer) # 0-23
    
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    #ORM
    todo = relationship("Todo")