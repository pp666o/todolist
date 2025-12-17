from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager

from . import models, database
from .services.engine_service import global_engine
from . import endpoints

#1.Auto create DB tables
models.Base.metadata.create_all(bind=database.engine)

#2. Lifespan - FastAPI 应用生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- 启动时执行 ---
    print("\n🚀 系统启动中...")
    
    #获取一个temporary数据库会话
    db = database.SessionLocal()
    try:
        #调用 Service 层的加载逻辑
        global_engine.reload_from_db(db)
    finally:
        db.close()
    
    yield #应用运行的时间
    
    # --- 关闭时执行 ---
    print("🛑 系统关闭。\n")

app = FastAPI(lifespan=lifespan)
app.include_router(endpoints.router) #register API routes

@app.get("/")
def root():
    return {"message": "System Ready. Go to /docs to test."}

#简单的测试接口：查看 C++ 引擎状态
@app.get("/engine/status")
def engine_status():
    #这里hack一下去访问私有变量(演示用的)
    count = global_engine._engine.size()
    return {"engine_item_count": count}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)