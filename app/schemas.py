from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

#user create todo request data
class TodoCreate(BaseModel):
    content: str
    start_time: datetime  # Format: 2025-12-14T10:00:00

#search request data
class SearchRequest(BaseModel):
    query: str
    start_time: datetime
    end_time: datetime
    top_k: int = 5

#return todo data
class TodoResponse(BaseModel):
    id: int
    content: str
    start_time: Optional[datetime]
    score: Optional[float] = None  #serach score
    class Config:
        from_attributes = True
#predict request data
class PredictRequest(BaseModel):
    content: str
    start_time: str | None = None