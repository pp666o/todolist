from .services.ml_engine import predictor
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from . import models, schemas, database, utils
from .services.engine_service import global_engine
from .services.ml_engine import global_model
from .services.redis_service import redis_client
from .services.ml_engine import predictor
from typing import List
import time
import random

router = APIRouter()

class AcceptOrderRequest(BaseModel):
    worker_id: str
    raw_payload: str  # 前端把原始的 JSON 字符串传回来，为“ticket”
    
class FaucetRequest(BaseModel):
    user_id: int

class BidRequest(BaseModel):
    user_id: str
    content: str
    bid_amount: int
    task_id: int | None = None

@router.post("/exchange/accept/")
async def accept_bid_order(req: AcceptOrderRequest):
    """
    接单/合拍接口
    """
    # 调用 Redis 进行原子结算
    success = await redis_client.settle_order(req.raw_payload, req.worker_id)
    
    if success:
        # 解析一下为了返回好消息
        import json
        data = json.loads(req.raw_payload)
        amount = data.get("bid")
        return {
            "status": "success", 
            "msg": f"🤝 合拍成功！你获得了 {amount} MAB 奖励。",
            "earned": amount
        }
    else:
        # 防止可能是手慢了，或者是自己的单
        raise HTTPException(
            status_code=400, 
            detail="合拍失败：订单已被抢走或不能接自己的单"
        )
        
@router.get("/balance/{user_id}")
async def get_user_balance(user_id: int):
    """
    查询用户余额
    修复点：直接调用 redis_client.get_balance，确保读取的是 'user_wallet:...'
    """
    try:
        #RedisService 接收的是 str 类型的 ID
        balance = await redis_client.get_balance(str(user_id))
        
        return {
            "user_id": user_id, 
            "balance": balance,
            "status": "normal"
        }
    except Exception as e:
        print(f"❌ 获取余额失败: {e}")
        return {"user_id": user_id, "balance": 0, "status": "error"}
    
@router.post("/mine/{user_id}")
async def mine_currency(user_id: int):
    """
    挖矿接口 (Target 4)
    功能：点击一次，给用户余额增加 100 MAB
    """
    try:
        # 1.get redis client
        redis = await redis_client.get_client()
        
        # 2.key point：务必必须一定！！！使用与 'get_user_balance' 接口完全一致的 Key
        # 之前定义的读取 Key 是: f"user:{user_id}:balance"
        key = f"user:{user_id}:balance"
        
        # 3.使用 Redis 的 incrby 原子操作增加金额
        # 如果 Key 不存在，Redis 会自动将其初始化为 0 然后加 100
        new_balance = await redis.incrby(key, 100)
        
        print(f"💰 用户 {user_id} 挖矿成功，当前余额: {new_balance}")
        
        return {
            "status": "success",
            "message": "Mining successful! +100 MAB",
            "added": 100,
            "balance": new_balance
        }
        
    except Exception as e:
        print(f"❌ 挖矿失败: {e}")
        return {"status": "error", "message": str(e)}
    
@router.post("/faucet/")
async def faucet_mining(req: FaucetRequest):
    """
    挖矿接口 (POST /mab/faucet/)
    修复点：调用 redis_client.add_mab 确保写入正确的 Key
    """
    try:
        user_id = req.user_id
        
        #直接调用 Service 里的加MBA方法，一次 +100
        #add_mab 内部已经封装了 incrby 和 Key 的拼接
        new_balance = await redis_client.add_mab(str(user_id), 100)
        
        print(f"💰 用户 {user_id} 挖矿成功 (+100)，当前余额: {new_balance}")
        
        return {
            "status": "success",
            "message": "Mining successful! +100 MAB",
            "added": 100,
            "balance": new_balance
        }
    except Exception as e:
        print(f"❌ 挖矿失败: {e}")
        return {"status": "error", "message": str(e)}
    
#同时修改获取列表的接口，改用 get_order_book_raw
@router.get("/exchange/board/")
async def get_exchange_board():
    """
    查看竞价板
    逻辑：从 Redis 读取数据 -> 字段补全 -> 返回给前端
    """
    try:
        # 1. 获取真实数据
        orders = await redis_client.get_order_book_raw(top_k=50)
        
        # 2. data washing and polyfill
        # 这一步是为了防止前端因为找不到 'user_id' 或 'amount' 而显示空白
        cleaned_orders = []
        for item in orders:
            if not isinstance(item, dict):
                continue
                
            # 补全：金主 ID
            if 'user_id' not in item:
                item['user_id'] = item.get('sponsor', 'Unknown')
            
            # 补全：金额
            if 'amount' not in item:
                item['amount'] = item.get('bid', 0)
                
            cleaned_orders.append(item)

        print(f"👀 [Market] 加载了 {len(cleaned_orders)} 条有效订单")

        # 3. 返回双重 Key，兼容前端的不同读取方式
        return {
            "list": cleaned_orders,   # 推荐用这个
            "market": cleaned_orders, # 兼容旧代码
            "status": "success"
        }
    except Exception as e:
        print(f"❌ 查询市场失败: {e}")
        return {"list": [], "market": []}
        
        # 3. 把假数据合并到列表里
        final_list = [mock_order] + real_orders
        
        # 4. 对真实数据也做字段补全 (防止真实数据字段缺胳膊少腿)
        for item in real_orders:
            if isinstance(item, dict):
                # 补全 sponsor -> user_id
                if "sponsor" in item and "user_id" not in item:
                    item["user_id"] = item["sponsor"]
                # 补全 bid -> amount
                if "bid" in item and "amount" not in item:
                    item["amount"] = item["bid"]
        
        print(f"🚀 返回给前端的总数据量: {len(final_list)} 条")
        
        # 5. 返回双重 Key 结构，确保前端能拿到
        return {
            "market": final_list,
            "list": final_list,
            "orders": final_list,
            "status": "success"
        }
        
    except Exception as e:
        print(f"❌ 查询市场失败: {e}")
        # 即使报错，也返回一个假数据看看能不能显示
        return {"market": [{"content": f"报错了: {e}", "bid": 0}], "list": []}

@router.post("/exchange/bid/")
async def place_bid_order(req: BidRequest):
    """
    发布竞价单 (Target 5 Update: 改为提交审核)
    """
    try:
        final_task_id = req.task_id if req.task_id is not None else int(time.time())

        # 1. 扣费 (保持不变)
        is_paid = await redis_client.deduct_mab(req.user_id, req.bid_amount)
        if not is_paid:
            raise HTTPException(status_code=400, detail="余额不足，请先挖矿！")

        # 2. CHANGE 提交审核，而不是直接 place_bid
        await redis_client.submit_for_audit(final_task_id, req.content, req.bid_amount, req.user_id)
        
        return {"status": "success", "message": "竞价单已提交审核，请等待管理员批准！"} # 提示语变了
    except Exception as e:
        return {"status": "error", "message": str(e)}

# 2. 新增审核接口
@router.get("/admin/pending/")
async def get_pending_list():
    """查看待审核列表"""
    ads = await redis_client.get_pending_ads()
    return {"pending": ads}

class AuditRequest(BaseModel):
    raw_payload: str
    action: str # "approve" or "reject"

@router.post("/admin/audit/")
async def audit_ad(req: AuditRequest):
    """审核操作"""
    if req.action == "approve":
        await redis_client.approve_ad(req.raw_payload)
        return {"status": "success", "msg": "已批准"}
    else:
        await redis_client.reject_ad(req.raw_payload)
        return {"status": "success", "msg": "已拒绝"}

# 3. CORE 修改获取 Todo 列表接口，注入广告
@router.get("/todos/", response_model=List[schemas.TodoResponse])
async def read_todos_mixed(skip: int = 0, limit: int = 100, db: Session = Depends(database.get_db)):
    """
    获取 Todo 列表 (Target 5: 智能混入广告)
    """
    # A. 获取真实任务
    todos = db.query(models.Todo).order_by(models.Todo.id.desc()).offset(skip).limit(limit).all()
    
    # 转换为 Pydantic/Dict 格式以便修改
    results = []
    for t in todos:
        results.append({
            "id": t.id,
            "content": t.content,
            "start_time": t.start_time,
            "created_at": t.created_at,
            "is_ad": False # 标记这是真任务
        })
        
    # B. Ad Injection 简单的广告注入逻辑
    # 逻辑：每隔 3 个任务，插 1 个广告
    try:
        # 获取所有活跃广告 (按出价从高到低)
        active_ads = await redis_client.get_order_book_raw(top_k=5) # 复用获取 Active 的逻辑
        
        if active_ads and len(results) > 0:
            # 拿出最贵的那个广告
            top_ad = active_ads[0]
            
            # 构造一个“伪造”的 Todo 对象
            ad_item = {
                "id": 99999, # 特殊 ID
                "content": f"📢 [推荐] {top_ad.get('content')} (赚 {top_ad.get('bid')} MAB)",
                "start_time": "推广",
                "created_at": None,
                "is_ad": True,
                "ad_payload": top_ad.get("_raw") # 方便前端点击接单
            }
            
            # 插入到列表第 2 位 (列表够长的话)
            if len(results) >= 1:
                results.insert(1, ad_item)
            else:
                results.append(ad_item)
                
    except Exception as e:
        print(f"⚠️ 广告注入失败: {e}")

    return results
    
# ---  make Todo API ---
@router.post("/todos/", response_model=schemas.TodoResponse)
async def create_todo(todo: schemas.TodoCreate, db: Session = Depends(database.get_db)):
    # 1. 存入 PostgreSQL
    db_todo = models.Todo(content=todo.content, start_time=todo.start_time)
    db.add(db_todo)
    db.commit()
    db.refresh(db_todo)

    # 2. 同步到 C++ 向量引擎
    vector = utils.get_embedding(db_todo.content)
    try:
        global_engine.add_todo(
            db_todo.id, 
            db_todo.content, 
            db_todo.created_at, 
            vector
        )
    except Exception as e:
        print(f"⚠️ C++同步失败: {e}")

    # 3. fix: Redis 热度统计 改成分词
    try:
        # 使用 ML 引擎的分词能力
        tags = predictor.extract_tags(db_todo.content)
        
        print(f"🔍 [分词热度] 原文: '{db_todo.content}' -> 标签: {tags}")
        
        for tag in tags:
            # 给每个标签都增加热度！
            # 比如 "吃火锅" -> 热度+1
            await redis_client.search_add(tag)
            
    except Exception as e:
        print(f"⚠️ Redis热度同步失败: {e}")

    return db_todo

@router.get("/todos/", response_model=List[schemas.TodoResponse])
def read_todos(skip: int = 0, limit: int = 100, db: Session = Depends(database.get_db)):
    """
    获取历史任务列表 (默认返回最近的 100 条)
    """
    # 倒序排列 (最新的在最前面)
    todos = db.query(models.Todo).order_by(models.Todo.id.desc()).offset(skip).limit(limit).all()
    return todos

# --- 2. mixable search API(Target 1)  ---
@router.post("/search/")
async def search_todos(request: schemas.SearchRequest):
    # 1. 转换向量
    query_vec = utils.get_embedding(request.query)
    
    # 2. 定义时间范围 (如果没有传，默认搜过去10年到未来1年)
    # C++ 需要的是整数时间戳
    current_ts = int(time.time())
    start_ts = 0 
    end_ts = current_ts + 31536000 # +1年
    
    # 3. 调用引擎 (传入 4 个参数)
    results = global_engine.search(start_ts, end_ts, query_vec, request.top_k)
    
    return {"results": results}

@router.post("/train/{user_id}")
def train_model(user_id: int, db: Session = Depends(database.get_db)):
    """
    触发机器学习训练。
    在真实系统中，这通常由后台定时任务(Cron Job)每天凌晨触发。
    """
    try:
        status = global_model.train(db, user_id)
        if status == "No Data":
            return {"status": "warning", "message": "数据不足，请先运行 mock_history.py 生成数据"}
        return {
            "status": "success", 
            "message": "模型训练完成", 
            "learned_clusters": global_model.cluster_map
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
class PredictRequest(BaseModel):
    content: str
    start_time: str | None = None
    
@router.get("/trending/")
async def get_trending_list():
    """获取全网热度榜"""
    try:
        # 调用 Redis 服务获取前 10 名
        data = await redis_client.get_trending(top_k=10)
        return data
    except Exception as e:
        print(f"❌ 获取热榜失败: {e}")
        return {"list": []}
    
@router.post("/predict/")
async def predict_next_step(request: PredictRequest):
    try:
        # 1. 准备兜底数据 (Redis)
        # (A) 获取全网热榜作为探出层
        trending_data = await redis_client.get_trending(top_k=3)
        hot_list = trending_data.get("list", [])
        
        # (B) 获取全局协同数据 (为了简化，这里暂时用 Mock，或者可能再建一个 Redis Hash存全局转移ß
        global_trans = {} 
        
        # 2. 调用预测
        result_text = predictor.predict(
            request.content, 
            global_transitions=global_trans,
            hot_list=hot_list
        )
        
        return {"result": result_text}
        
    except Exception as e:
        return {"result": f"预测系统故障: {str(e)}"}
    
@router.get("/explore/trending")
async def get_trending_now():
    """
    全网热度排行榜 (Top 10)
    数据源：Redis Sorted Set
    """
    try:
        redis = await redis_client.get_client()
        
        # ZREVRANGE: 从大到小取前 10 名
        # withscores=True 会同时返回分数
        items = await redis.zrevrange("global_trend", 0, 9, withscores=True)
        
        # Format response to frontpanel
        # items : [('健身', 5.0), ('写代码', 3.0)]
        result = [
            {"rank": i+1, "content": name, "hot_index": int(score)} 
            for i, (name, score) in enumerate(items)
        ]
        return {"title": "🔥 全网热门挑战", "list": result}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}
        
@router.post("/train/")
def train_model(db: Session = Depends(database.get_db)):
    """
    触发机器学习训练：从数据库读取所有数据 -> 训练 K-Means/Markov -> 保存模型
    """
    try:
        # 1. 捞出所有数据
        todos = db.query(models.Todo).all()
        if len(todos) < 3:
            return {"status": "error", "message": "数据太少，再多创建几条任务吧 (至少3条)"}
            
        # 2. 转换数据格式给 ML 引擎
        # 假设 ml_engine 需要 list of dict
        data_for_ml = [
            {"content": t.content, "start_time": t.start_time} 
            for t in todos
        ]
        
        # 3. 开始训练
        result = predictor.train(data_for_ml)
        return {"status": "success", "message": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.delete("/todos/{todo_id}")
def delete_todo(todo_id: int, db: Session = Depends(database.get_db)):
    # 1. 查库：确保任务存在
    db_todo = db.query(models.Todo).filter(models.Todo.id == todo_id).first()
    if not db_todo:
        raise HTTPException(status_code=404, detail="Task not found")
    
    try:
        # 尝试删除关联数据
        db.query(models.Interaction).filter(models.Interaction.todo_id == todo_id).delete()
        
        # 2. 只有关联数据删干净了，才能删除主任务
        db.delete(db_todo)
        db.commit()
        
        # C++ 引擎同步删除 (如果有接口的话，目前没有只能忽略)
        
        return {"status": "success", "message": f"Task {todo_id} deleted"}
        
    except Exception as e:
        db.rollback() # 出错回滚
        print(f"❌ 删除失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))