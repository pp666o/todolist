import sys
import os
import time
from app import models

#path os manipulation to import C++ module
current_dir = os.path.dirname(os.path.abspath(__file__))
cpp_core_path = os.path.join(current_dir, "../../cpp_core")
if cpp_core_path not in sys.path:
    sys.path.append(cpp_core_path)

#import C++ todo_core module
try:
    import todo_core # type: ignore
except ImportError:
    todo_core = None

#engine service class
class VectorEngine:
    def __init__(self):
        self.core = None
        if todo_core:
            try:
                # fix 1: Class name must be TodoEngine (TO -> matcher.cpp)
                self.core = todo_core.TodoEngine()
                print(">>> [C++ Engine] Core initialized successfully (TodoEngine).")
            except Exception as e:
                print(f"❌ [C++ Engine] 初始化失败: {e}")
                print(f"    模块内容: {dir(todo_core)}") #debug
        else:
            print("⚠️ [C++ Engine] 模块未导入，运行在降级模式")

    def reload_from_db(self, db_session):
        """从数据库全量加载数据"""
        if not self.core:
            return
            
        try:
            query = db_session.query(models.Todo).yield_per(1000)
            count = 0
            for todo in query:
                if todo.embedding is not None and todo.created_at is not None:
                    # fix 2: change time stamps (C++ endd long long)
                    ts = int(todo.created_at.timestamp())
                    
                    # fix 3: put 4 parameters
                    self.core.add_todo(todo.id, ts, todo.content, todo.embedding)
                    count += 1
            print(f">>> [C++ Engine] Reloaded {count} items.")
        except Exception as e:
            print(f"❌ [C++ Engine] 重载数据失败: {e}")

    def search(self, start_ts: int, end_ts: int, query_vector: list, top_k: int = 5):
        """
        调用 C++ 进行检索 (支持时间范围)
        """
        if not self.core:
            return []
        
        try:
            # get C++: search(start_ts, end_ts, vector, topk)
            # Notice强调！：直接透传 endpoint 传过来的 start_ts 和 end_ts
            return self.core.search(start_ts, end_ts, query_vector, top_k)
        except Exception as e:
            print(f"❌ [C++ Engine] 搜索失败: {e}")
            return []

    def add_todo(self, todo_id: int, content: str, created_at, vector: list):
        """
        实时添加任务
        注意：参数变多了，因为 C++ 引擎现在更强大了，需要存内容和时间
        """
        if not self.core:
            return

        if vector is not None:
            try:
                #set timestamp
                ts = int(created_at.timestamp()) if created_at else int(time.time())
                
                #get C++ API right
                self.core.add_todo(todo_id, ts, content, vector)
                print(f">>> [C++ Engine] Added item {todo_id} to memory.")
            except Exception as e:
                print(f"❌ [C++ Engine] 添加任务失败: {e}")

global_engine = VectorEngine()