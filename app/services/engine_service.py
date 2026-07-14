from __future__ import annotations

import os
import sys
import time

from app import models


current_dir = os.path.dirname(os.path.abspath(__file__))
cpp_core_path = os.path.abspath(
    os.path.join(current_dir, "../../cpp_core")
)

if cpp_core_path not in sys.path:
    sys.path.append(cpp_core_path)

try:
    import todo_core  # type: ignore
except ImportError:
    todo_core = None


class VectorEngine:
    def __init__(self) -> None:
        self.core = None

        if todo_core is None:
            print("⚠️ [C++ Engine] 模块未导入，运行在降级模式")
            return

        try:
            self.core = todo_core.TodoEngine()
            print(
                ">>> [C++ Engine] "
                "Core initialized successfully (TodoEngine)."
            )
        except Exception as exc:
            print(f"❌ [C++ Engine] 初始化失败: {exc}")
            print(f"    模块内容: {dir(todo_core)}")

    def reload_from_db(self, db_session) -> int:
        """清空内存索引，然后从 PostgreSQL 全量恢复。"""
        if self.core is None:
            return 0

        try:
            self.core.clear()

            query = (
                db_session.query(models.Todo)
                .filter(
                    models.Todo.embedding.isnot(None),
                    models.Todo.created_at.isnot(None),
                )
                .yield_per(1000)
            )

            count = 0

            for todo in query:
                timestamp = int(todo.created_at.timestamp())

                self.core.upsert_todo(
                    todo.id,
                    timestamp,
                    todo.content,
                    todo.embedding,
                )
                count += 1

            print(
                f">>> [C++ Engine] Reloaded {count} items. "
                f"Current size={self.core.size()}."
            )
            return count

        except Exception as exc:
            print(f"❌ [C++ Engine] 重载数据失败: {exc}")
            return 0

    def search(
        self,
        start_ts: int,
        end_ts: int,
        query_vector: list[float],
        top_k: int = 5,
    ):
        if self.core is None:
            return []

        try:
            return self.core.search(
                start_ts,
                end_ts,
                query_vector,
                top_k,
            )
        except Exception as exc:
            print(f"❌ [C++ Engine] 搜索失败: {exc}")
            return []

    def upsert_todo(
        self,
        todo_id: int,
        content: str,
        created_at,
        vector: list[float],
    ) -> bool:
        if self.core is None or vector is None:
            return False

        try:
            timestamp = (
                int(created_at.timestamp())
                if created_at
                else int(time.time())
            )

            inserted = self.core.upsert_todo(
                todo_id,
                timestamp,
                content,
                vector,
            )

            action = "Inserted" if inserted else "Updated"
            print(
                f">>> [C++ Engine] "
                f"{action} item {todo_id}. "
                f"Current size={self.core.size()}."
            )
            return True

        except Exception as exc:
            print(f"❌ [C++ Engine] Upsert 失败: {exc}")
            return False

    def add_todo(
        self,
        todo_id: int,
        content: str,
        created_at,
        vector: list[float],
    ) -> bool:
        # 兼容现有 endpoint；实际执行 upsert。
        return self.upsert_todo(
            todo_id,
            content,
            created_at,
            vector,
        )

    def remove_todo(self, todo_id: int) -> bool:
        if self.core is None:
            return False

        try:
            removed = bool(self.core.remove_todo(todo_id))

            print(
                f">>> [C++ Engine] Remove item {todo_id}: "
                f"removed={removed}, "
                f"current_size={self.core.size()}."
            )
            return removed

        except Exception as exc:
            print(f"❌ [C++ Engine] 删除失败: {exc}")
            return False

    def clear(self) -> None:
        if self.core is not None:
            self.core.clear()

    def size(self) -> int:
        if self.core is None:
            return 0

        return int(self.core.size())


global_engine = VectorEngine()
