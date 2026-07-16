from fastapi import APIRouter, HTTPException, Query, Path, Body, BackgroundTasks
from typing import List, Dict, Optional, Union, Set
from pydantic import BaseModel, Field, validator
import datetime
import sys
import os
import asyncio
from pathlib import Path as PathLibPath
from app.utils.data_loader import load_data_from_files, add_interactions_to_engine, format_user_id

# 添加项目根目录到系统路径 (根据实际结构调整)
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir))) # 假设 api 在 app 下一级
sys.path.append(project_root)

from ..core.recommendation_engine import RecommendationEngine
from ..api.matching_api import matching_engine # <-- 导入 matching_engine

# 初始化空的引擎实例，数据将在启动时加载
recommendation_engine = RecommendationEngine()

router = APIRouter(prefix="/recommendation", tags=["recommendation"])

# --- 添加启动时加载数据的函数 ---
async def load_engine_data():
    """从本地文件加载推荐引擎数据"""
    print("--- [API Startup] 开始加载推荐引擎数据 ---")

    # 使用共享数据加载模块
    users_data, items_data, interactions_data = await load_data_from_files()

    print(f"--- [API Startup] 加载到推荐引擎中: {len(users_data)}用户, {len(items_data)}物品, {len(interactions_data)}交互 ---")
    try:
        if users_data:
            recommendation_engine.add_batch_user_profiles(users_data)
            print(f"--- [API Startup] 添加 {len(users_data)} 用户到推荐引擎 ---")
        
        if items_data:
            recommendation_engine.add_batch_item_profiles(items_data)
            print(f"--- [API Startup] 添加 {len(items_data)} 物品到推荐引擎 ---")
        
        if interactions_data:
            # 使用共享函数添加交互数据
            count = add_interactions_to_engine(recommendation_engine, interactions_data)
            print(f"--- [API Startup] 添加 {count}/{len(interactions_data)} 交互到推荐引擎 ---")
        
        if not users_data and not items_data and not interactions_data:
            print("--- [API Startup] 没有数据加载到推荐引擎 ---")
        else:
            print("--- [API Startup] 推荐引擎数据加载完成 ---")

    except Exception as e:
        print(f"--- [API Startup] 推荐引擎数据加载失败: {e} ---")

# --- 注册 FastAPI 启动事件 ---
@router.on_event("startup")
async def startup_event():
    """FastAPI 应用启动时触发"""
    print("--- [API Startup] 安排推荐引擎数据加载任务 --- ")
    await load_engine_data()
    print("--- [API Startup] 推荐引擎数据加载任务完成. 服务器就绪. ---")

"""
推荐API提供以下功能:
1. 获取个性化推荐 - /get_recommendations
   - 支持多种推荐策略混合
   - 支持上下文感知推荐
   - 支持动态用户匹配推荐
   - 支持自适应流行度权重调整
   
示例请求:
{
  "user_id": "user123",
  "context": {
    "location": "home",
    "time_of_day": "evening",
    "device": "mobile"
  },
  "count": 10,
  "include_user_matches": true,
  "max_user_matches": 2,
  "strategy_weights": {
    "collaborative": 0.6,
    "content": 0.3,
    "context": 0.1
  },
  "popularity_preference": -0.5  // 偏好较冷门的内容
}

popularity_preference参数说明:
- 取值范围: -1.0到1.0
- -1.0: 完全偏好冷门内容，显著降低热门内容分数
- 0.0: 中性，不调整流行度影响
- 1.0: 完全偏好热门内容，显著提升热门内容分数
- 不提供此参数时将自动根据用户历史行为推断偏好

2. 记录用户交互 - /record_interaction
   - 支持多种交互类型记录
   - 用于实时更新用户偏好模型
"""

# 数据模型
class UserContext(BaseModel):
    location: Optional[str] = None
    location_type: Optional[str] = None
    device: Optional[str] = None
    time: Optional[str] = None
    time_of_day: Optional[str] = None
    hour_of_day: Optional[int] = None
    activity: Optional[str] = None

class PotentialUserMatch(BaseModel):
    user_id: str
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    profile_url: Optional[str] = None
    bio: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    location: Optional[str] = None
    interests: List[str] = []
    match_score: float = 0.5
    common_friends: int = 0
    social_activity_level: Optional[float] = None
    response_rate: Optional[float] = None
    preferred_activities: List[str] = []
    active_times: List[str] = []

class RecommendationRequest(BaseModel):
    user_id: str
    limit: int = Field(10, ge=1, le=100)
    exclude_seen: bool = True
    scenario: Optional[str] = Field(None, description="推荐场景，如：'home', 'personal', 'group'等")
    item_type: Optional[str] = Field(None, description="物品类型过滤")
    adaptive_factor: Optional[float] = Field(0.5, ge=0, le=1, description="自适应因子，控制个性化与多样性")
    category_filters: Optional[List[str]] = Field(None, description="物品类别过滤")
    min_rating: Optional[float] = Field(None, ge=0, le=5, description="最低评分过滤")

class MixedRecommendationRequest(BaseModel):
    user_id: str
    other_user_id: Optional[str] = Field(None, description="二人推荐的第二用户ID")
    limit: int = Field(10, ge=1, le=100)
    exclude_seen: bool = True
    scenario: Optional[str] = Field("mixed", description="推荐场景，默认为'mixed'")
    item_type: Optional[str] = Field(None, description="物品类型过滤")
    adaptive_factor: Optional[float] = Field(0.5, ge=0, le=1, description="自适应因子，控制个性化与多样性")
    similarity_weight: Optional[float] = Field(0.5, ge=0, le=1, description="对用户相似度的权重")
    complementarity_weight: Optional[float] = Field(0.5, ge=0, le=1, description="对用户互补性的权重")
    category_filters: Optional[List[str]] = Field(None, description="物品类别过滤")
    min_rating: Optional[float] = Field(None, ge=0, le=5, description="最低评分过滤")

@router.post("/get-recommendations", response_model=Dict)
async def get_recommendations(request: RecommendationRequest):
    """获取个性化推荐"""
    try:
        # 检查用户ID格式，如果是纯数字，添加前缀
        user_id = request.user_id
        formatted_user_id = format_user_id(user_id)
    
        print(f"--- Getting recommendations for user {user_id} with params: limit={request.limit}, exclude_seen={request.exclude_seen}, scenario={request.scenario}, item_type={request.item_type}, adaptive_factor={request.adaptive_factor} ---")
        
        recommendations = recommendation_engine.get_recommendations(
            user_id=formatted_user_id,
            limit=request.limit,
            exclude_seen=request.exclude_seen,
            item_type=request.item_type,
            adaptive_factor=request.adaptive_factor,
            category_filters=request.category_filters,
            min_rating=request.min_rating,
            scenario=request.scenario
        )

        print(f"--- Generated {len(recommendations)} recommendations for user {user_id} ---")
        
        # 格式化响应
        response = {
            "user_id": user_id,  # 保持返回原始ID
            "recommendation_count": len(recommendations),
            "scenario": request.scenario or "default",
            "recommendations": recommendations
        }
        
        return response
    except KeyError as ke:
        print(f"获取推荐失败 - 用户或资源不存在: {ke}")
        raise HTTPException(status_code=404, detail=f"用户或资源不存在: {ke}")
    except Exception as e:
        print(f"获取推荐失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取推荐失败: {str(e)}")

@router.post("/get-mixed-recommendations", response_model=Dict)
async def get_mixed_recommendations(request: MixedRecommendationRequest):
    """获取混合推荐：单人或两人场景"""
    try:
        # 检查用户ID格式，如果是纯数字，添加前缀
        user_id = request.user_id
        formatted_user_id = format_user_id(user_id)
        
        # 单人推荐场景
        if request.other_user_id is None:
            print(f"--- Getting personal recommendations for user {user_id} ---")
            
            recommendations = recommendation_engine.get_recommendations(
                user_id=formatted_user_id,
                limit=request.limit,
                exclude_seen=request.exclude_seen,
                item_type=request.item_type,
                adaptive_factor=request.adaptive_factor,
                category_filters=request.category_filters,
                min_rating=request.min_rating,
                scenario=request.scenario
            )
            
            response = {
                "user_id": user_id,
                "recommendation_type": "personal",
                "recommendation_count": len(recommendations),
                "recommendations": recommendations
            }
        else:
            # 二人推荐场景
            other_user_id = request.other_user_id
            formatted_other_user_id = format_user_id(other_user_id)
            
            print(f"--- Getting pair recommendations for users {user_id} and {other_user_id} ---")
            
            recommendations = recommendation_engine.get_recommendations_for_pair(
                user_id1=formatted_user_id,
                user_id2=formatted_other_user_id,
                limit=request.limit,
                exclude_seen=request.exclude_seen,
                item_type=request.item_type,
                similarity_weight=request.similarity_weight,
                complementarity_weight=request.complementarity_weight,
                adaptive_factor=request.adaptive_factor,
                category_filters=request.category_filters,
                min_rating=request.min_rating
            )
            
            response = {
                "user_id": user_id,
                "other_user_id": other_user_id,
                "recommendation_type": "pair",
                "recommendation_count": len(recommendations),
                "recommendations": recommendations
            }
        
        print(f"--- Generated {len(recommendations)} recommendations ---")
        return response
        
    except KeyError as ke:
        print(f"获取混合推荐失败 - 用户或资源不存在: {ke}")
        raise HTTPException(status_code=404, detail=f"用户或资源不存在: {ke}")
    except Exception as e:
        print(f"获取混合推荐失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取混合推荐失败: {str(e)}")

@router.post("/get-similar-items/{item_id}", response_model=Dict)
async def get_similar_items(
    item_id: str = Path(..., description="物品ID"),
    limit: int = Query(10, ge=1, le=100, description="返回的数量")
):
    """获取与指定物品相似的其他物品"""
    try:
        print(f"--- Getting similar items for item {item_id} with limit={limit} ---")
        
        similar_items = recommendation_engine.get_similar_items(
            item_id=item_id,
            limit=limit
        )
        
        print(f"--- Found {len(similar_items)} similar items for item {item_id} ---")
        
        return {
            "item_id": item_id,
            "similar_items_count": len(similar_items),
            "similar_items": similar_items
        }
    except KeyError as ke:
        print(f"获取相似物品失败 - 物品不存在: {ke}")
        raise HTTPException(status_code=404, detail=f"物品不存在: {ke}")
    except Exception as e:
        print(f"获取相似物品失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取相似物品失败: {str(e)}")

@router.get("/trending-items", response_model=Dict)
async def get_trending_items(
    limit: int = Query(10, ge=1, le=100, description="返回的数量"),
    item_type: Optional[str] = Query(None, description="物品类型过滤"),
    time_window: str = Query("week", description="时间窗口，如：'day', 'week', 'month'")
):
    """获取当前热门物品"""
    try:
        print(f"--- Getting trending items with limit={limit}, item_type={item_type}, time_window={time_window} ---")
        
        trending_items = recommendation_engine.get_trending_items(
            limit=limit,
            item_type=item_type,
            time_window=time_window
        )
        
        print(f"--- Found {len(trending_items)} trending items ---")
        
        return {
            "trending_items_count": len(trending_items),
            "time_window": time_window,
            "trending_items": trending_items
        }
    except Exception as e:
        print(f"获取热门物品失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取热门物品失败: {str(e)}")

@router.get("/popular-items", response_model=Dict)
async def get_popular_items(
    limit: int = Query(10, ge=1, le=100, description="返回的数量"),
    item_type: Optional[str] = Query(None, description="物品类型过滤")
):
    """获取总体最受欢迎的物品"""
    try:
        print(f"--- Getting popular items with limit={limit}, item_type={item_type} ---")
        
        popular_items = recommendation_engine.get_popular_items(
            limit=limit,
            item_type=item_type
        )
        
        print(f"--- Found {len(popular_items)} popular items ---")
        
        return {
            "popular_items_count": len(popular_items),
            "popular_items": popular_items
        }
    except Exception as e:
        print(f"获取受欢迎物品失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取受欢迎物品失败: {str(e)}")

@router.get("/explore", response_model=Dict)
async def explore_recommendations(
    user_id: str,
    diversity_level: float = Query(0.7, ge=0, le=1, description="多样性水平"),
    limit: int = Query(10, ge=1, le=50, description="返回的数量"),
    item_type: Optional[str] = Query(None, description="物品类型过滤")
):
    """探索性推荐 - 提供更多样化和新颖的推荐"""
    try:
        # 检查用户ID格式，如果是纯数字，添加前缀
        formatted_user_id = format_user_id(user_id)
    
        print(f"--- Getting exploratory recommendations for user {user_id} with diversity_level={diversity_level}, limit={limit}, item_type={item_type} ---")
        
        explore_items = recommendation_engine.get_exploratory_recommendations(
            user_id=formatted_user_id,
            diversity_level=diversity_level,
            limit=limit,
            item_type=item_type
        )
        
        print(f"--- Generated {len(explore_items)} exploratory recommendations ---")
        
        return {
            "user_id": user_id,
            "diversity_level": diversity_level,
            "recommendation_count": len(explore_items),
            "recommendations": explore_items
        }
    except KeyError as ke:
        print(f"获取探索推荐失败 - 用户不存在: {ke}")
        raise HTTPException(status_code=404, detail=f"用户不存在: {ke}")
    except Exception as e:
        print(f"获取探索推荐失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取探索推荐失败: {str(e)}")

@router.post("/record_user_interaction")
async def record_user_interaction(
    user_id: str,
    target_user_id: str,
    interaction_type: str = Query(..., description="交互类型: view, like, message, connect, dismiss"),
    timestamp: Optional[str] = None
):
    """记录用户与推荐用户的交互"""
    try:
        # 解析时间戳，如果未提供则使用当前时间
        interaction_time = datetime.datetime.now()
        if timestamp:
            try:
                interaction_time = datetime.datetime.fromisoformat(timestamp)
            except ValueError:
                pass
        
        # 这里模拟记录交互的操作
        # 实际环境中应该将交互数据持久化存储
        
        return {"success": True, "message": f"成功记录与用户{target_user_id}的{interaction_type}交互"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"记录交互失败: {str(e)}")