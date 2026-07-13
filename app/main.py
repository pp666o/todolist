from fastapi import FastAPI
from contextlib import asynccontextmanager
from .database import engine, Base, SessionLocal
from .endpoints import router
from .services.redis_service import redis_client #redis service
from .services.engine_service import global_engine

#创建数据库表
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---lunaching processing---
    print("\n🚀 系统启动中...")
    
    # A.连接 Redis
    await redis_client.connect()
    
    # B.加载 C++ 检索引擎
    db = SessionLocal()
    try:
        print(">>> [Core] 正在从数据库重载向量索引...")
        global_engine.reload_from_db(db)
    except Exception as e:
        print(f"⚠️ 索引加载警告: {e}")
    finally:
        db.close()
    
    yield # 应用运行
    
    # --- 🛑 关闭时执行 ---
    print("🛑 系统关闭中...")
    
    # C. 断开 Redis 连接
    await redis_client.close()
    print("👋 Redis 连接已断开")

app = FastAPI(lifespan=lifespan)
app.include_router(router)

@app.get("/")
def root():
    return {"message": "System Ready. Go to /docs to test."}

#简单的测试接口：查看 C++ 引擎状态
@app.get("/engine/status")
def engine_status():
    #这里hack一下去访问私有变量(演示用的)
    count = global_engine.core.size() if global_engine.core else 0
    return {"engine_item_count": count}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)