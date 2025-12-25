from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

# user create todo request data
class TodoCreate(BaseModel):
    content: str
    start_time: datetime | None = None

# search request data
class SearchRequest(BaseModel):
    query: str
    start_time: datetime | str | None = None 
    end_time: datetime | str | None = None
    top_k: int = 5

# return todo data
class TodoResponse(BaseModel):
    id: int
    content: str  # !!必须包含此字段，且不能为空
    
    created_at: datetime | None = None
    
    # core fixes:
    # 1. 补回 start_time 字段，否则前端拿不到时间
    # 2. 允许 str 类型，因为广告注入时 start_time 是 "推广" 字符串
    start_time: datetime | str | None = None 
    
    # new string
    is_ad: bool = False
    ad_payload: str | None = None

    class Config:
        # 允许从 ORM 对象读取 data
        from_attributes = True

# predict request data
class PredictRequest(BaseModel):
    content: str
    start_time: str | None = None
    
class AuditRequest(BaseModel):
    raw_payload: str
    action: str  # "approve" or "reject"