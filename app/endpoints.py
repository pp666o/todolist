from .services.ml_engine import predictor
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from . import models, schemas, database, utils
from .services.engine_service import global_engine
from .services.ml_engine import global_model
from .services.redis_service import redis_manager
from typing import List
import time

router = APIRouter()

# --- 1. make Todo API ---
@router.post("/todos/", response_model=schemas.TodoResponse)
async def create_todo(todo: schemas.TodoCreate, db: Session = Depends(database.get_db)):
    # 1. store PostgreSQL
    #compute embedding vector
    vector = utils.get_embedding(todo.content)
    
    db_todo = models.Todo(
        content=todo.content, 
        start_time=todo.start_time,
        embedding=vector
    )
    db.add(db_todo)
    db.commit()
    db.refresh(db_todo)
    
    # 2.sync to C++ engine
    try:
        global_engine.add_todo(
            db_todo.id, 
            db_todo.content, 
            db_todo.created_at, 
            vector
        )
    except Exception as e:
        print(f"⚠️ C++同步失败: {e}")

    # 3. add new todo to Redis global trend ranking
    try:
        # get redis client
        redis = await redis_manager.get_client()
        
        # ZINCRBY: 有序集合自增
        # Key: "global_trend" (排行榜的名字)
        # Amount: 1 (热度加 1)
        # Member: todo.content (比如 "健身")
        await redis.zincrby("global_trend", 1, todo.content)
        print(f">>> [Redis] '{todo.content}' 热度 +1")
    except Exception as e:
        print(f"⚠️ Redis 统计失败: {e}")
        
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

@router.post("/predict/")
def predict_next_step(request: PredictRequest):
    """
    预测接口：真正调用 ML 引擎
    """
    try:
        # 打印一下，确认接口被调用了
        print(f"📡 [API] 收到预测请求: {request.content}")
        
        # 1. 调用引擎进行预测
        result_text = predictor.predict(request.content)
        
        # 2. 返回结果
        return {"result": result_text}
        
    except Exception as e:
        print(f"❌ 预测接口报错: {e}")
        return {"result": f"预测出错: {str(e)}"}
    
@router.get("/explore/trending")
async def get_trending_now():
    """
    全网热度排行榜 (Top 10)
    数据源：Redis Sorted Set
    """
    try:
        redis = await redis_manager.get_client()
        
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