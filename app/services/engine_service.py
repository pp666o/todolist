import sys
import os
import time
from sqlalchemy.orm import Session
from app.models import Todo

current_dir = os.path.dirname(os.path.abspath(__file__))
cpp_core_path = os.path.join(current_dir, "../../cpp_core")
sys.path.append(cpp_core_path)

try:
    import todo_core
except ImportError:
    print("❌ 严重错误: 无法导入 C++ 模块 'todo_core'。请确保已在 cpp_core 目录下运行编译命令。")
    sys.exit(1)

class VectorEngine:
    _instance = None
    _engine = None

    def __new__(cls):
        """单例模式：确保全局只有一个 C++ 引擎实例"""
        if cls._instance is None:
            cls._instance = super(VectorEngine, cls).__new__(cls)
            print(">>> [System] 初始化 C++ 检索引擎...")
            cls._engine = todo_core.TodoEngine()
        return cls._instance

    def reload_from_db(self, db: Session):
        """
        核心逻辑：从 Postgres 读取所有数据，格式化后灌入 C++
        """
        print(">>> [Sync] 开始从数据库加载数据到内存...")
        start_time = time.time()
        
        #1. 查询所有 Todo
        todos = db.query(Todo).all()
        
        count = 0
        for t in todos:
            #data transfer format:
            #Python datetime -> Unix Timestamp (long long)
            #PGVector -> List[float]
            
            if not t.start_time:
                continue # 如果没有时间，无法进行时间范围匹配，跳过
                
            ts = int(t.start_time.timestamp())
            
            #处理向量转换 (pgvector 在 python 中为 list 或 numpy array)
            #这里的 .tolist() 是为了保险，确保传给 C++ 是一组纯浮点数
            vec_data = t.embedding
            if hasattr(vec_data, 'tolist'):
                vec_data = vec_data.tolist()
            
            self._engine.add_todo(t.id, ts, t.content, vec_data)
            count += 1
            
        duration = time.time() - start_time
        print(f">>> [Sync] 加载完成！共 {count} 条数据，耗时 {duration:.4f}秒。")
        print(f">>> [Engine] 当前引擎内数据量: {self._engine.size()}")

    def add_single_todo(self, todo: Todo):
        """当用户创建新 Todo 时调用，增量更新 C++"""
        if not todo.start_time:
            return
        ts = int(todo.start_time.timestamp())
        vec = todo.embedding
        if hasattr(vec, 'tolist'):
            vec = vec.tolist()
        self._engine.add_todo(todo.id, ts, todo.content, vec)

    def search(self, start_ts, end_ts, query_vec, top_k=5):
        """暴露给 API 的搜索接口"""
        return self._engine.search(start_ts, end_ts, query_vec, top_k)

#global singleton instance
global_engine = VectorEngine()