from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from . import models, schemas, database, utils
from .services.engine_service import global_engine
from .services.ml_engine import global_model

router = APIRouter()

# --- 1. make Todo API ---
@router.post("/todos/", response_model=schemas.TodoResponse)
def create_todo(todo: schemas.TodoCreate, db: Session = Depends(database.get_db)):
    # A.Make embedding vector
    vector = utils.get_embedding(todo.content)
    
    #B.store to PostgreSQL
    db_todo = models.Todo(
        content=todo.content,
        start_time=todo.start_time,
        embedding=vector  #store pgvector text format
    )
    db.add(db_todo)
    db.commit()
    db.refresh(db_todo) #get assigned id
    
    #C.Update C++ Engine
    global_engine.add_single_todo(db_todo)
    
    return db_todo

# --- 2. mixable search API(Target 1)  ---
@router.post("/search/", response_model=list[schemas.TodoResponse])
def search_todos(request: schemas.SearchRequest):
    #A.make embedding vector for query
    query_vec = utils.get_embedding(request.query)
    
    #B.convert time to timestamp
    start_ts = int(request.start_time.timestamp())
    end_ts = int(request.end_time.timestamp())
    
    #using C++ engine to search
    #return: [(id, score, content), ...]
    results = global_engine.search(start_ts, end_ts, query_vec, request.top_k)
    
    #D. format response
    response_list = []
    for tid, score, content in results:
        #这里可以直接用 C++ 返回的 content，也可以去 DB查详情
        #为演示速度，直接构造返回
        response_list.append(schemas.TodoResponse(
            id=tid,
            content=content,
            start_time=None, #C++ demo版暂存简单数据，如需完整时间可回查DB
            score=score
        ))
        
    return response_list

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

@router.post("/predict/")
def predict_next(request: schemas.TodoCreate, db: Session = Depends(database.get_db)):
    """
    预测接口：告诉系统你刚完成了什么，系统猜你下一步做什么。
    """
    #1.Let user input content, get embedding
    vector = utils.get_embedding(request.content)
    
    #2.input to ML model for prediction
    recommendation = global_model.predict(vector)
    
    if recommendation:
        return {"result": recommendation}
    else:
        return {"result": "暂无高置信度推荐，随便做点什么吧！"}