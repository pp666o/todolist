from fastapi import APIRouter, HTTPException, Query, Body, Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
import datetime
import asyncio
from app.core.user_matching_engine import UserMatchingEngine
from app.utils.data_loader import load_data_from_files, add_interactions_to_engine, format_user_id

router = APIRouter(prefix="/matching", tags=["matching"])

# 初始化匹配引擎 (使其可在外部导入)
matching_engine = UserMatchingEngine()

# --- 添加启动时加载数据的函数 --- 
async def load_engine_data():
    """从本地文件加载匹配引擎数据"""
    print("--- [API Startup] 开始加载匹配引擎数据 ---")

    # 使用共享数据加载模块
    users_data, items_data, interactions_data = await load_data_from_files()

    print(f"--- [API Startup] 加载到匹配引擎中: {len(users_data)}用户, {len(items_data)}物品, {len(interactions_data)}交互 ---")
    try:
        if users_data:
            matching_engine.add_batch_user_profiles(users_data)
            print(f"--- [API Startup] 添加 {len(users_data)} 用户到匹配引擎 ---")
        
        if items_data:
            matching_engine.add_batch_item_profiles(items_data)
            print(f"--- [API Startup] 添加 {len(items_data)} 物品到匹配引擎 ---")
        
        if interactions_data:
            # 使用共享函数添加交互数据
            count = add_interactions_to_engine(matching_engine, interactions_data)
            print(f"--- [API Startup] 添加 {count}/{len(interactions_data)} 交互到匹配引擎 ---")
        
        if not users_data and not items_data and not interactions_data:
            print("--- [API Startup] 没有数据加载到匹配引擎 ---")
        else:
            print("--- [API Startup] 匹配引擎数据加载完成 ---")
            
    except Exception as e:
        print(f"--- [API Startup] 匹配引擎数据加载失败: {e} ---")

# --- 注册 FastAPI 启动事件 --- 
@router.on_event("startup")
async def startup_event():
    """FastAPI 应用启动时触发"""
    print("--- [API Startup] 安排匹配引擎数据加载任务 --- ")
    await load_engine_data()
    print("--- [API Startup] 匹配引擎数据加载任务完成. 服务器就绪. ---")

# 数据模型
class UserProfile(BaseModel):
    user_id: str
    gender: str
    age: int
    interests: List[str] = []
    preferences: Optional[Dict] = None
    
class ItemProfile(BaseModel):
    item_id: str
    name: str
    type: str
    tags: List[str] = []
    target_gender: Optional[str] = None
    target_age_min: Optional[int] = None
    target_age_max: Optional[int] = None
    couples_score: float = 0.0
    details: Optional[Dict] = None
    
class UserInteraction(BaseModel):
    user_id: str
    item_id: str
    interaction_type: str
    score: float = 1.0
    
class UserBatchRequest(BaseModel):
    users: List[UserProfile]
    
class ItemBatchRequest(BaseModel):
    items: List[ItemProfile]
    
class MatchingResponse(BaseModel):
    success: bool
    result: Dict
    message: str

@router.post("/users", response_model=MatchingResponse)
async def add_users(request: UserBatchRequest):
    """批量添加用户资料"""
    try:
        users = []
        for user in request.users:
            user_dict = user.dict()
            users.append(user_dict)
            
        matching_engine.add_batch_user_profiles(users)
        
        return {
            "success": True,
            "result": {
                "user_count": len(users)
            },
            "message": f"成功添加{len(users)}个用户资料"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"添加用户资料失败: {str(e)}")

@router.post("/items", response_model=MatchingResponse)
async def add_items(request: ItemBatchRequest):
    """批量添加物品资料"""
    try:
        items = []
        for item in request.items:
            item_dict = item.dict()
            items.append(item_dict)
            
        matching_engine.add_batch_item_profiles(items)
        
        return {
            "success": True,
            "result": {
                "item_count": len(items)
            },
            "message": f"成功添加{len(items)}个物品资料"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"添加物品资料失败: {str(e)}")

@router.post("/interactions", response_model=MatchingResponse)
async def add_interaction(interaction: UserInteraction):
    """添加用户-物品交互"""
    try:
        matching_engine.add_user_item_interaction(
            user_id=interaction.user_id,
            item_id=interaction.item_id,
            interaction_type=interaction.interaction_type,
            score=interaction.score
        )
        
        return {
            "success": True,
            "result": {
                "user_id": interaction.user_id,
                "item_id": interaction.item_id
            },
            "message": "成功添加用户-物品交互"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"添加用户-物品交互失败: {str(e)}")

@router.get("/user-similarity/{user_id1}/{user_id2}", response_model=Dict)
async def get_user_similarity(
    user_id1: str = Path(..., description="第一个用户ID"),
    user_id2: str = Path(..., description="第二个用户ID")
):
    """获取两个用户之间的相似度"""
    try:
        # 检查用户ID格式并进行转换
        formatted_user_id1 = user_id1
        formatted_user_id2 = user_id2
        
        if user_id1.isdigit() or (user_id1.startswith('0') and user_id1[1:].isdigit()):
            formatted_user_id1 = f"user_{user_id1.zfill(4)}"
            
        if user_id2.isdigit() or (user_id2.startswith('0') and user_id2[1:].isdigit()):
            formatted_user_id2 = f"user_{user_id2.zfill(4)}"
    
        similarity = matching_engine.calculate_user_similarity(formatted_user_id1, formatted_user_id2)
        
        return {
            "user_id1": user_id1,
            "user_id2": user_id2,
            "similarity": similarity
        }
    except KeyError as ke:
        print(f"用户相似度计算失败 - 用户不存在: {ke}")
        raise HTTPException(status_code=404, detail=f"用户不存在: {ke}")
    except Exception as e:
        print(f"计算用户相似度失败: {e}")
        raise HTTPException(status_code=500, detail=f"计算用户相似度失败: {str(e)}")

@router.get("/user-complementarity/{user_id1}/{user_id2}", response_model=Dict)
async def get_user_complementarity(
    user_id1: str = Path(..., description="第一个用户ID"),
    user_id2: str = Path(..., description="第二个用户ID")
):
    """获取两个用户之间的互补性"""
    try:
        # 检查用户ID格式并进行转换
        formatted_user_id1 = user_id1
        formatted_user_id2 = user_id2
        
        if user_id1.isdigit() or (user_id1.startswith('0') and user_id1[1:].isdigit()):
            formatted_user_id1 = f"user_{user_id1.zfill(4)}"
            
        if user_id2.isdigit() or (user_id2.startswith('0') and user_id2[1:].isdigit()):
            formatted_user_id2 = f"user_{user_id2.zfill(4)}"
    
        complementarity = matching_engine.calculate_complementarity(formatted_user_id1, formatted_user_id2)
        
        return {
            "user_id1": user_id1,
            "user_id2": user_id2,
            "complementarity": complementarity
        }
    except KeyError as ke:
        print(f"用户互补性计算失败 - 用户不存在: {ke}")
        raise HTTPException(status_code=404, detail=f"用户不存在: {ke}")
    except Exception as e:
        print(f"计算用户互补性失败: {e}")
        raise HTTPException(status_code=500, detail=f"计算用户互补性失败: {str(e)}")

@router.get("/common-interests/{user_id1}/{user_id2}", response_model=Dict)
async def get_common_interests(
    user_id1: str = Path(..., description="第一个用户ID"),
    user_id2: str = Path(..., description="第二个用户ID")
):
    """获取两个用户的共同兴趣"""
    try:
        # 检查用户ID格式并进行转换
        formatted_user_id1 = user_id1
        formatted_user_id2 = user_id2
        
        if user_id1.isdigit() or (user_id1.startswith('0') and user_id1[1:].isdigit()):
            formatted_user_id1 = f"user_{user_id1.zfill(4)}"
            
        if user_id2.isdigit() or (user_id2.startswith('0') and user_id2[1:].isdigit()):
            formatted_user_id2 = f"user_{user_id2.zfill(4)}"
    
        common_interests = matching_engine.find_common_interests(formatted_user_id1, formatted_user_id2)
        
        return {
            "user_id1": user_id1,
            "user_id2": user_id2,
            "common_interests": common_interests,
            "count": len(common_interests)
        }
    except KeyError as ke:
        print(f"获取共同兴趣失败 - 用户不存在: {ke}")
        raise HTTPException(status_code=404, detail=f"用户不存在: {ke}")
    except Exception as e:
        print(f"获取共同兴趣失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取共同兴趣失败: {str(e)}")

@router.get("/potential-matches/{user_id}", response_model=Dict)
async def find_potential_matches(
    user_id: str = Path(..., description="用户ID"),
    top_k: int = Query(10, ge=1, le=100, description="返回的匹配数量"),
    min_similarity: float = Query(0.3, ge=0, le=1, description="最小相似度阈值"),
    min_complementarity: float = Query(0.3, ge=0, le=1, description="最小互补度阈值"),
    gender_filter: Optional[str] = Query(None, description="性别过滤条件")
):
    """查找用户的潜在匹配对象"""
    try:
        # 使用通用ID格式化函数
        formatted_user_id = format_user_id(user_id)
            
        print(f"--- Finding potential matches for user {user_id} with params: top_k={top_k}, min_similarity={min_similarity}, min_complementarity={min_complementarity}, gender_filter={gender_filter} ---")
        
        matches = matching_engine.find_potential_matches(
            user_id=formatted_user_id,  # 使用格式化后的ID
            top_k=top_k,
            min_similarity=min_similarity,
            min_complementarity=min_complementarity,
            gender_filter=gender_filter
        )
        
        print(f"--- Found {len(matches)} potential matches for user {user_id} ---")
        
        return {
            "user_id": user_id,  # 保持返回原始ID
            "match_count": len(matches),
            "matches": matches
        }
    except KeyError as ke:
        print(f"查找潜在匹配失败 - 用户不存在: {ke}")
        raise HTTPException(status_code=404, detail=f"用户不存在: {ke}")
    except Exception as e:
        print(f"查找潜在匹配失败: {e}")
        raise HTTPException(status_code=500, detail=f"查找潜在匹配失败: {str(e)}")

@router.get("/recommend-for-pair/{user_id1}/{user_id2}", response_model=Dict)
async def recommend_for_pair(
    user_id1: str = Path(..., description="第一个用户ID"),
    user_id2: str = Path(..., description="第二个用户ID"),
    item_type: Optional[str] = Query(None, description="物品类型过滤"),
    top_k: int = Query(10, ge=1, le=100, description="返回的推荐数量")
):
    """为一对用户推荐共同的物品/活动"""
    try:
        # 检查用户ID格式并进行转换
        formatted_user_id1 = user_id1
        formatted_user_id2 = user_id2
        
        if user_id1.isdigit() or (user_id1.startswith('0') and user_id1[1:].isdigit()):
            formatted_user_id1 = f"user_{user_id1.zfill(4)}"
            
        if user_id2.isdigit() or (user_id2.startswith('0') and user_id2[1:].isdigit()):
            formatted_user_id2 = f"user_{user_id2.zfill(4)}"
    
        print(f"--- Generating recommendations for user pair {user_id1} and {user_id2} with item_type={item_type}, top_k={top_k} ---")
        
        recommendations = matching_engine.recommend_items_for_pair(
            user_id1=formatted_user_id1,
            user_id2=formatted_user_id2,
            item_type=item_type,
            top_k=top_k
        )
        
        print(f"--- Generated {len(recommendations)} recommendations for user pair ---")
        
        return {
            "user_id1": user_id1,
            "user_id2": user_id2,
            "recommendation_count": len(recommendations),
            "recommendations": recommendations
        }
    except KeyError as ke:
        print(f"为用户对推荐物品失败 - 用户不存在: {ke}")
        raise HTTPException(status_code=404, detail=f"用户不存在: {ke}")
    except Exception as e:
        print(f"为用户对推荐物品失败: {e}")
        raise HTTPException(status_code=500, detail=f"为用户对推荐物品失败: {str(e)}")

@router.get("/relationship-compatibility/{user_id1}/{user_id2}", response_model=Dict)
async def get_relationship_compatibility(
    user_id1: str = Path(..., description="第一个用户ID"),
    user_id2: str = Path(..., description="第二个用户ID")
):
    """获取两个用户之间的关系兼容性分析"""
    try:
        # 检查用户ID格式并进行转换
        formatted_user_id1 = user_id1
        formatted_user_id2 = user_id2
        
        if user_id1.isdigit() or (user_id1.startswith('0') and user_id1[1:].isdigit()):
            formatted_user_id1 = f"user_{user_id1.zfill(4)}"
            
        if user_id2.isdigit() or (user_id2.startswith('0') and user_id2[1:].isdigit()):
            formatted_user_id2 = f"user_{user_id2.zfill(4)}"
            
        compatibility = matching_engine.get_relationship_compatibility(formatted_user_id1, formatted_user_id2)
        
        # 获取两个用户的性格特质数据
        user1_traits = matching_engine.user_profiles[formatted_user_id1].get('personality_traits', {})
        user2_traits = matching_engine.user_profiles[formatted_user_id2].get('personality_traits', {})
        
        # 添加性格特质数据到响应中
        compatibility['personality_traits'] = {
            'user1': user1_traits,
            'user2': user2_traits
        }
        
        return {
            "user_id1": user_id1,
            "user_id2": user_id2,
            "compatibility": compatibility
        }
    except KeyError as ke:
        print(f"获取关系兼容性失败 - 用户不存在: {ke}")
        raise HTTPException(status_code=404, detail=f"用户不存在: {ke}")
    except Exception as e:
        print(f"获取关系兼容性分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取关系兼容性分析失败: {str(e)}")

@router.get("/match-dashboard/{user_id1}/{user_id2}", response_model=Dict)
async def get_match_dashboard(
    user_id1: str = Path(..., description="第一个用户ID"),
    user_id2: str = Path(..., description="第二个用户ID")
):
    """获取两个用户的匹配仪表板数据"""
    try:
        print(f"--- Generating match dashboard for users {user_id1} and {user_id2} ---")
        
        # 检查用户ID格式并进行转换
        formatted_user_id1 = user_id1
        formatted_user_id2 = user_id2
        
        if user_id1.isdigit() or (user_id1.startswith('0') and user_id1[1:].isdigit()):
            formatted_user_id1 = f"user_{user_id1.zfill(4)}"
            
        if user_id2.isdigit() or (user_id2.startswith('0') and user_id2[1:].isdigit()):
            formatted_user_id2 = f"user_{user_id2.zfill(4)}"
        
        # 获取多项匹配数据
        similarity = matching_engine.calculate_user_similarity(formatted_user_id1, formatted_user_id2)
        complementarity = matching_engine.calculate_complementarity(formatted_user_id1, formatted_user_id2)
        common_interests = matching_engine.find_common_interests(formatted_user_id1, formatted_user_id2)
        compatibility = matching_engine.get_relationship_compatibility(formatted_user_id1, formatted_user_id2)
        
        # 获取推荐
        recommendations = matching_engine.recommend_items_for_pair(
            user_id1=formatted_user_id1,
            user_id2=formatted_user_id2,
            top_k=5  # 增加推荐数量以便分类筛选
        )
        
        # 筛选不同类型的推荐
        activities = [r for r in recommendations if r.get("details", {}).get("type") == "activity"]
        travel = [r for r in recommendations if r.get("details", {}).get("type") == "travel"]
        
        dashboard = {
            "match_summary": {
                "user_id1": user_id1,
                "user_id2": user_id2,
                "compatibility_score": compatibility["compatibility_score"],
                "compatibility_level": compatibility["compatibility_level"],
                "relationship_type": compatibility["relationship_type"],
                "common_interests_count": len(common_interests)
            },
            "detailed_metrics": {
                "similarity": similarity,
                "complementarity": complementarity["complementarity_score"],
                "common_interests": common_interests
            },
            "top_recommendations": {
                "activities": activities[:1] if activities else [],
                "travel": travel[:1] if travel else [],
                "general": recommendations[:1] if recommendations else []
            }
        }
        
        print(f"--- Match dashboard generated successfully ---")
        
        return dashboard
    except KeyError as ke:
        print(f"获取匹配仪表板失败 - 用户不存在: {ke}")
        raise HTTPException(status_code=404, detail=f"用户不存在: {ke}")
    except Exception as e:
        print(f"获取匹配仪表板失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取匹配仪表板失败: {str(e)}") 