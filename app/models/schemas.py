from pydantic import Field
from pydantic_settings import BaseSettings
from typing import Dict, Any, Union, Optional, List
from datetime import datetime

class UserActivity(BaseSettings):
    user_id: int
    timestamp: datetime
    activity_type: str
    session_id: str
    ip_address: str

class ProcessedActivity(BaseSettings):
    user_id: int
    activity_count: int
    activity_types: Dict[str, int]
    first_activity: datetime
    last_activity: datetime
    session_count: int
    unique_ips: List[str]
    device_summary: Dict[str, Any] = Field(default_factory=dict)
    window_start: datetime
    window_end: datetime

class ActivityMetrics(BaseSettings):
    total_activities: int
    unique_users: int
    activity_distribution: Dict[str, int]
    hourly_distribution: Dict[int, int]
    average_session_duration: float

class ActivityType(BaseSettings):
    # 根据具体需求定义活动类型属性
    type: str

class DataLakeSettings(BaseSettings):

    # Spark配置：添加 warehouse 键
    SPARK_CONFIG: Dict[str, Any] = Field(default_factory=lambda: {
        "spark.master": "local[*]",
        "spark.app.name": "GravityWall-DataLake",
        "spark.sql.extensions": "io.delta.sql.DeltaSparkSessionExtension",
        "spark.sql.catalog.spark_catalog": "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        "spark.sql.catalog.spark_catalog.warehouse": "/path/to/iceberg/warehouse"
    })
    
    # 存储配置
    STORAGE_CONFIG: Dict[str, str] = Field(default_factory=lambda: {
        "base_path": "/data/datalake",
        "raw_zone": "raw",
        "processed_zone": "processed",
        "curated_zone": "curated"
    })
    
    # 流处理配置
    STREAMING_CONFIG: Dict[str, Any] = Field(default_factory=lambda: {
        "kafka_brokers": "localhost:9092",
        "kafka_topic_prefix": "gravitywall",
        "checkpoint_interval": 5000
    })
    
    class Config:
        env_file = ".env"

settings = DataLakeSettings()


# --- 新增数据模型 ---

class User(BaseSettings):
    user_id: Union[int, str] = Field(..., description="用户唯一标识符")
    name: Optional[str] = Field(None, description="姓名")
    age: Optional[int] = Field(None, description="年龄")
    gender: Optional[str] = Field(None, description="性别")
    location: Optional[str] = Field(None, description="地点")
    occupation: Optional[str] = Field(None, description="职业")
    interests: List[str] = Field(default_factory=list, description="兴趣列表")
    personality_traits: Dict[str, float] = Field(default_factory=dict, description="五大性格特征得分")
    # 可以添加更多特征...

class Item(BaseSettings):
    item_id: Union[int, str] = Field(..., description="物品唯一标识符")
    name: Optional[str] = Field(None, description="名称")
    category: Optional[str] = Field(None, description="类别")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    description: Optional[str] = Field(None, description="描述")
    release_year: Optional[int] = Field(None, description="发布年份")
    popularity_score: Optional[float] = Field(None, description="流行度分数")
    # 可以添加更多特征...

class Interaction(BaseSettings):
    user_id: Union[int, str] = Field(..., description="用户ID")
    item_id: Union[int, str] = Field(..., description="物品ID")
    rating: Optional[float] = Field(None, description="评分 (例如 1.0-5.0)")
    interaction_type: Optional[str] = Field(None, description="交互类型 (e.g., view, click, rate)")
    timestamp: datetime = Field(default_factory=datetime.now, description="交互时间戳")

# --- 结束新增 ---