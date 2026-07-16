from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse
import os
from app.api import recommendation_api, matching_api
import uvicorn # 添加 uvicorn 导入以便直接运行

# --- 配置前端文件路径 ---
# 假设前端构建后的文件在 frontend/dist 目录下
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend", "dist")
INDEX_HTML = os.path.join(FRONTEND_DIR, "index.html")

# 创建 FastAPI 应用实例
app = FastAPI(
    title="Recommendation & Matching System API",
    description="Provides personalized recommendations and user matching.",
    version="0.1.0"
)

# --- 添加 CORS 中间件 ---
# 允许所有来源 (开发时方便，生产环境应更严格)
origins = ["*"] # 或者指定前端开发服务器地址，如 "http://localhost:5173"

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # 允许所有方法
    allow_headers=["*"], # 允许所有头部
)
# --- 结束 CORS 配置 ---

# 包含 API 路由 (放在 CORS 之后)
app.include_router(recommendation_api.router)
app.include_router(matching_api.router)

@app.get("/api", tags=["Root"])
async def read_api_root():
    """API 根路径，返回欢迎信息"""
    return {"message": "Welcome to the Recommendation & Matching System API backend!"}

# --- 配置静态文件服务和根路由 ---
# 挂载静态文件目录 (注意：路径是相对于 FastAPI 运行的位置)
# 如果 frontend/dist 存在，则挂载
if os.path.exists(FRONTEND_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_vue_app(full_path: str):
        """处理所有非 API 路由，返回 Vue 应用的 index.html"""
        # 检查请求的是否是已知的静态文件（虽然上面挂载了/assets，但以防万一）
        # 如果不是 API 路由，则返回 index.html，让 Vue Router 处理
        if not full_path.startswith("/api") and not full_path.startswith("/docs") and not full_path.startswith("/openapi.json") and os.path.exists(INDEX_HTML):
             # 检查请求的文件是否存在于 dist 目录中
             requested_path = os.path.join(FRONTEND_DIR, full_path)
             if os.path.exists(requested_path) and os.path.isfile(requested_path):
                  return FileResponse(requested_path)
             # 如果文件不存在或请求根路径，返回 index.html
             return FileResponse(INDEX_HTML)
        # 对于 API 路由或其他 FastAPI 已处理的路由，返回 404 或让 FastAPI 处理
        # (实际上 Fastapi 会先匹配 /api 等，到这里基本就是前端路由了)
        if os.path.exists(INDEX_HTML):
             return FileResponse(INDEX_HTML)
        else:
             # 如果前端文件不存在，返回一个简单的提示
             return {"message": "Frontend not built or found. API is running."} # Fallback if index.html doesn't exist
else:
    print(f"[WARNING] Frontend directory not found at {FRONTEND_DIR}. Static file serving disabled.")
    @app.get("/", tags=["Root"], include_in_schema=False)
    async def read_root_no_frontend():
        return {"message": "API is running, but frontend build is not available."}
# --- 结束静态文件配置 ---

# --- 添加直接运行的功能 (可选) ---
# 允许通过 python main.py 启动服务
if __name__ == "__main__":
    print("Starting server via main.py...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 