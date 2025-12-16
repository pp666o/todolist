from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from . import models, schemas, database, utils
from .services.engine_service import global_engine

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
        #这里可以直接用 C++ 返回的 content，也可以去 DB 查详情
        #为演示速度，直接构造返回
        response_list.append(schemas.TodoResponse(
            id=tid,
            content=content,
            start_time=None, #C++ demo版暂存简单数据，如需完整时间可回查DB
            score=score
        ))
        
    return response_list