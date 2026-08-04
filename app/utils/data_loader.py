import json
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

from app.infrastructure.postgres import connect_postgres


def format_user_id(user_id: str) -> str:
    """
    格式化用户ID，确保符合数据库中存储的格式
    如果用户ID是纯数字（例如'0001'或'123'），转换为'user_XXXX'格式
    
    参数:
        user_id: 输入的用户ID字符串
        
    返回:
        str: 格式化后的用户ID
    """
    if user_id.isdigit() or (user_id.startswith('0') and user_id[1:].isdigit()):
        return f"user_{user_id.zfill(4)}"
    return user_id

async def load_data_from_files() -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    从本地JSON文件加载用户、物品和交互数据
    
    返回:
        Tuple[List[Dict], List[Dict], List[Dict]]: 用户数据、物品数据和交互数据
    """
    print("--- [Data Loader] 开始从本地文件加载数据 ---")

    # 获取项目根目录和数据目录
    project_root_dir = Path(__file__).resolve().parent.parent.parent
    data_dir = project_root_dir / "data"
    users_file = data_dir / "users.json"
    items_file = data_dir / "items.json"
    interactions_file = data_dir / "interactions.json"

    users_data = []
    items_data = []
    interactions_data = []

    try:
        if users_file.exists():
            with open(users_file, 'r', encoding='utf-8') as f:
                users_data = json.load(f)
            print(f"--- [Data Loader] Loaded {len(users_data)} users from {users_file} ---")
        else:
            print(f"--- [Data Loader] Warning: Users data file not found at {users_file} ---")

        if items_file.exists():
            with open(items_file, 'r', encoding='utf-8') as f:
                items_data = json.load(f)
            print(f"--- [Data Loader] Loaded {len(items_data)} items from {items_file} ---")
        else:
            print(f"--- [Data Loader] Warning: Items data file not found at {items_file} ---")

        if interactions_file.exists():
            with open(interactions_file, 'r', encoding='utf-8') as f:
                interactions_data = json.load(f)
            print(f"--- [Data Loader] Loaded {len(interactions_data)} interactions from {interactions_file} ---")
        else:
            print(f"--- [Data Loader] Warning: Interactions data file not found at {interactions_file} ---")

    except Exception as e:
        print(f"--- [Data Loader] Error loading data from files: {e} ---")
        
    print(f"--- [Data Loader] 数据加载完成: {len(users_data)} 用户, {len(items_data)} 物品, {len(interactions_data)} 交互 ---")
    
    return users_data, items_data, interactions_data


def _age_bucket_to_numeric(age_bucket: Optional[str]) -> int | None:
    if age_bucket is None:
        return None

    mapping = {
        "18-24": 21,
        "25-34": 29,
        "35-44": 39,
        "45-54": 49,
        "55-64": 59,
        "65+": 70,
        "unknown": None,
    }

    return mapping.get(age_bucket)


async def load_user_profiles_from_postgres() -> List[Dict[str, Any]]:
    """Load user profiles from PostgreSQL and normalize them for the matching engine."""
    async with await connect_postgres() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                """
                SELECT
                    source_user_id,
                    source,
                    age_bucket,
                    job,
                    education,
                    hobby_tags,
                    character_tag,
                    user_level,
                    country,
                    province,
                    city,
                    district,
                    school,
                    authored_post_count,
                    category_weights,
                    tag_weights,
                    avg_likes,
                    avg_views,
                    avg_marks,
                    avg_dislikes,
                    avg_rate_score,
                    last_authored_at,
                    profile_version,
                    source_updated_at,
                    synced_at
                FROM public.user_profiles
                """,
            )
            rows = await cursor.fetchall()

    profiles: List[Dict[str, Any]] = []

    for row in rows:
        source_user_id = row.get("source_user_id")
        if source_user_id is None:
            continue

        user_id = format_user_id(str(source_user_id))
        profile: Dict[str, Any] = {
            "user_id": user_id,
            "source": row.get("source"),
            "age_bucket": row.get("age_bucket"),
            "age": _age_bucket_to_numeric(row.get("age_bucket")),
            "job": row.get("job"),
            "education": row.get("education"),
            "hobby_tags": row.get("hobby_tags") or [],
            "character_tag": row.get("character_tag"),
            "user_level": row.get("user_level"),
            "country": row.get("country"),
            "province": row.get("province"),
            "city": row.get("city"),
            "district": row.get("district"),
            "school": row.get("school"),
            "authored_post_count": row.get("authored_post_count"),
            "category_weights": row.get("category_weights") or {},
            "tag_weights": row.get("tag_weights") or {},
            "avg_likes": row.get("avg_likes"),
            "avg_views": row.get("avg_views"),
            "avg_marks": row.get("avg_marks"),
            "avg_dislikes": row.get("avg_dislikes"),
            "avg_rate_score": row.get("avg_rate_score"),
            "last_authored_at": row.get("last_authored_at"),
            "profile_version": row.get("profile_version"),
            "source_updated_at": row.get("source_updated_at"),
            "synced_at": row.get("synced_at"),
        }
        profiles.append(profile)

    return profiles


def add_interactions_to_engine(engine: Any, interactions_data: List[Dict]) -> int:
    """
    将交互数据添加到引擎中
    
    参数:
        engine: 引擎实例，必须有 add_user_item_interaction 方法
        interactions_data: 交互数据列表
        
    返回:
        int: 成功添加的交互数量
    """
    count = 0
    for interaction in interactions_data:
        # 检查必须字段是否存在
        user_id = interaction.get('user_id')
        item_id = interaction.get('item_id')
        interaction_type = interaction.get('interaction_type')
        score = interaction.get('score', 1.0)  # 使用默认值

        if user_id and item_id and interaction_type:
            try:
                engine.add_user_item_interaction(
                    user_id=user_id,
                    item_id=item_id,
                    interaction_type=interaction_type,
                    score=score
                )
                count += 1
            except Exception as e:
                print(f"--- [Data Loader] Error adding interaction ({user_id}, {item_id}): {e} ---")
        else:
            print(f"--- [Data Loader] Skipping interaction due to missing fields: {interaction} ---")
    
    return count 