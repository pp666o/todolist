# TodoList CPython V1.0.0

## 1. 项目简介

TodoList CPython V1.0.0 是一个围绕 To-do List 场景构建的功能验证型项目。当前版本在基础待办事项之上，组合了中文语义检索、行为预测、Redis 热榜、MAB 虚拟钱包、任务竞价、广告审核与桌面端演示能力。

当前项目定位为：

> 用于验证 To-do List 在语义检索、行为预测、任务撮合和广告竞价场景中的单机原型。

当前阶段的首要任务是接入真实数据，完成字段映射、批量导入、向量生成和基础检索验证。

---

## 2. 当前已实现能力

### 2.1 To-do List 基础功能

- 创建 Todo
- 查询 Todo 列表
- 删除 Todo
- 保存 Todo 内容
- 保存开始时间和创建时间

### 2.2 中文语义向量

项目使用以下 SentenceTransformer 模型：

```text
paraphrase-multilingual-MiniLM-L12-v2
```

每条文本会被编码为 384 维向量，用于语义相似度检索。

### 2.3 C++ 向量检索

`cpp_core/matcher.cpp` 通过 pybind11 编译为 Python 扩展。

当前检索过程：

```text
查询文本
→ 生成 384 维向量
→ C++ 全量计算余弦相似度
→ 按得分排序
→ 返回 Top K
```

该实现适合 Demo 和小规模数据验证，不适合直接承载大规模线上数据。

### 2.4 Redis 热榜

创建 Todo 时，系统使用 Jieba 分词，并将关键词写入 Redis Sorted Set。

当前热榜 Key：

```text
todo_trending
```

### 2.5 行为预测原型

项目中包含两类实验：

1. 基于关键词转移关系的马尔可夫预测
2. 基于文本向量聚类和转移矩阵的行为预测

真实用户行为尚未形成完整闭环。

### 2.6 MAB 钱包与任务竞价

项目使用 Redis 实现：

- 用户余额查询
- 领取 MAB
- 发布竞价任务
- 广告审核
- 竞价任务展示
- 用户接单
- 接单奖励结算

### 2.7 桌面客户端

`todolist.py` 是 Tkinter 桌面端，包含：

- Todo 创建与展示
- 语义搜索
- 热门关键词
- 行为预测
- 用户切换
- MAB 钱包
- 竞价任务发布
- 广告审核
- 任务接单

---

## 3. 技术栈

| 模块 | 技术 |
|---|---|
| API 服务 | FastAPI |
| ORM | SQLAlchemy |
| 主数据库 | PostgreSQL |
| 向量字段 | pgvector |
| 在线缓存 | Redis |
| 文本向量 | SentenceTransformers |
| 中文分词 | Jieba |
| 机器学习 | scikit-learn |
| 检索实验 | C++、pybind11 |
| 桌面客户端 | Tkinter |

---

## 4. 项目目录

```text
.
├── app/
│   ├── database.py
│   ├── embedder.py
│   ├── endpoints.py
│   ├── main.py
│   ├── models.py
│   ├── schemas.py
│   ├── utils.py
│   └── services/
│       ├── engine_service.py
│       ├── ml_engine.py
│       └── redis_service.py
├── cpp_core/
│   ├── matcher.cpp
│   └── setup.py
├── mock_history.py
├── requirements.txt
├── todolist.py
└── README.md
```

目录说明：

- `app/`：FastAPI 服务、数据库模型和业务逻辑
- `app/services/`：向量检索、行为模型和 Redis 服务
- `cpp_core/`：C++ 向量检索模块
- `mock_history.py`：模拟历史行为数据
- `todolist.py`：桌面演示客户端
- `requirements.txt`：Python 依赖
- `README.md`：项目说明文档

---

## 5. 数据模型

### 5.1 todos

| 字段 | 说明 |
|---|---|
| `id` | Todo 主键 |
| `content` | Todo 文本 |
| `embedding` | 384 维文本向量 |
| `start_time` | 用户设定的开始时间 |
| `created_at` | 数据创建时间 |

### 5.2 interactions

| 字段 | 说明 |
|---|---|
| `id` | 行为主键 |
| `user_id` | 用户 ID |
| `todo_id` | Todo ID |
| `action_type` | 行为类型 |
| `day_of_week` | 星期特征 |
| `hour_of_day` | 小时特征 |
| `timestamp` | 行为发生时间 |

当前预留的行为类型：

```text
complete
view
reject
```

后续可扩展：

```text
exposure
click
collect
comment
accept
unlock
```

---

## 6. 主要数据流

### 6.1 Todo 创建链路

```text
客户端提交 Todo
→ FastAPI 接收请求
→ PostgreSQL 保存数据
→ SentenceTransformer 生成向量
→ C++ 内存引擎增加索引
→ Jieba 提取关键词
→ Redis 更新热度
```

### 6.2 搜索链路

```text
用户输入查询文本
→ 生成查询向量
→ C++ 引擎计算余弦相似度
→ 返回 Top K
```

### 6.3 广告竞价链路

```text
用户领取 MAB
→ 发布竞价任务
→ 扣除余额
→ 进入审核队列
→ 管理员批准
→ 进入竞价市场
→ 广告混入 Todo 列表
→ 其他用户接单
→ 接单用户获得 MAB
```

---

## 7. 环境要求

建议：

```text
Python 3.10+
PostgreSQL 14+
Redis 6+
C++11 编译器
```

安装依赖：

```bash
python -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
pip install pybind11
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install -r requirements.txt
pip install pybind11
```

---

## 8. PostgreSQL 与 pgvector

创建数据库：

```sql
CREATE DATABASE todo_db;
```

启用 pgvector：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

当前 PostgreSQL 配置位于：

```text
app/database.py
```

当前默认配置：

```text
postgresql://localhost/todo_db
```

接入真实数据库时，不要把账号和密码写入 README 或提交到 Git。后续建议改为读取环境变量：

```text
DATABASE_URL
```

---

## 9. Redis

当前 Redis 配置位于：

```text
app/services/redis_service.py
```

默认地址：

```text
redis://localhost
```

连接测试：

```bash
redis-cli ping
```

正常返回：

```text
PONG
```

后续建议改为读取环境变量：

```text
REDIS_URL
```

---

## 10. 编译 C++ 扩展

```bash
cd cpp_core
python setup.py build_ext --inplace
cd ..
```

编译成功后会生成：

```text
todo_core*.so
```

Windows 下通常为：

```text
todo_core*.pyd
```

未成功编译时，系统会进入降级模式，语义检索不可用。

---

## 11. 启动项目

启动后端：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

引擎状态：

```text
http://127.0.0.1:8000/engine/status
```

启动桌面客户端：

```bash
python todolist.py
```

---

## 12. 主要 API

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/todos/` | 创建 Todo |
| `GET` | `/todos/` | 查询 Todo |
| `DELETE` | `/todos/{todo_id}` | 删除 Todo |
| `POST` | `/search/` | 语义搜索 |
| `POST` | `/train/` | 训练关键词行为模型 |
| `POST` | `/train/{user_id}` | 训练用户聚类行为模型 |
| `POST` | `/predict/` | 预测下一步 Todo |
| `GET` | `/trending/` | 热门关键词 |
| `GET` | `/balance/{user_id}` | 查询 MAB |
| `POST` | `/faucet/` | 领取 MAB |
| `POST` | `/exchange/bid/` | 发布竞价任务 |
| `GET` | `/exchange/board/` | 查询竞价市场 |
| `POST` | `/exchange/accept/` | 接单 |
| `GET` | `/admin/pending/` | 查询待审核广告 |
| `POST` | `/admin/audit/` | 审核广告 |

当前 Router 同时注册到了根路径和 `/mab` 前缀，因此部分接口可能存在两套路径，后续需要统一。

---

# 13. 当前阶段：真实数据接入

## 13.1 接入原则

第一阶段不要直接全量导入所有数据，应按照以下顺序：

```text
确认数据源
→ 确认字段
→ 抽取小样本
→ 清洗与映射
→ 分批导入
→ 生成向量
→ 验证检索
→ 再扩大数据量
```

建议规模：

```text
第一批：1,000 条
第二批：10,000 条
第三批：全量数据
```

在 1,000 条数据尚未通过验收前，不进行全量导入。

## 13.2 最小字段要求

| 目标字段 | 必须 | 说明 |
|---|---:|---|
| `content` | 是 | 文本向量与检索 |
| `start_time` | 否 | 任务计划时间 |
| `created_at` | 建议 | 数据创建时间 |
| `source_id` | 建议 | 原始数据主键 |

如果接入帖子数据，可按以下方式映射：

| 原始字段 | Todo 字段 |
|---|---|
| 标题 + 正文 | `content` |
| 发布时间 | `created_at` |
| 计划时间或活动时间 | `start_time` |
| 帖子 ID | `source_id` |

当前 `todos` 表没有 `source` 和 `source_id`。正式接入外部数据前，建议增加：

```text
source
source_id
```

用于标识数据来源和防止重复导入。

## 13.3 接入前必须确认

```text
1. 数据库类型
2. 数据库地址与端口
3. 数据库名与表名
4. 主键字段
5. 标题和正文字段
6. 创建时间字段
7. 计划时间字段
8. 用户 ID 字段
9. 类别、标签字段
10. 经纬度字段
11. 总数据量
12. 增量同步方式
```

账号、密码和密钥必须通过环境变量或本地配置传入，不能写入 README 和代码仓库。

## 13.4 批量读取方式

不要使用一次性全表读取：

```python
query.all()
```

建议：

```text
按主键分页
批量读取
批量生成向量
批量写入
保存 checkpoint
失败后继续
```

建议批次大小：

```text
500～2,000 条/批
```

## 13.5 建议新增导入脚本

在暂不调整项目结构的情况下，在项目根目录新增：

```text
import_todo_data.py
```

该脚本负责：

```text
读取源数据
→ 文本清洗
→ 字段映射
→ 批量生成 embedding
→ 写入 todos
→ 保存最后处理的 source_id
```

不要把全量导入写进 FastAPI 启动流程。

## 13.6 导入后验收

每批导入后检查：

```text
导入数量
失败数量
重复数量
空文本数量
向量缺失数量
时间解析失败数量
数据库总行数
搜索结果是否合理
C++ 引擎加载数量
接口响应时间
```

---

## 14. 当前已知问题

1. 创建 Todo 时生成的 embedding 没有写回 PostgreSQL。
2. 服务启动时会通过 `.all()` 全量读取 Todo 并加载到 C++ 内存。
3. 搜索接口没有真正使用用户传入的时间范围。
4. C++ 检索使用全量遍历，不适合大规模数据。
5. 删除 Todo 后不会同步删除 C++ 内存索引。
6. 客户端“完成任务”实际是删除 Todo，没有写入 `interactions`。
7. `/todos/` 路由重复定义。
8. Router 同时注册到根路径和 `/mab`。
9. 两个 MAB 接口使用不同 Redis Key。
10. 广告审核拒绝后暂未退款。
11. 当前没有真实地理位置、人物画像、帖子分类和图检索。
12. 当前没有 A/B Test、曝光日志和完整离线评估链路。

---

## 15. 数据规模注意事项

当前 C++ 检索复杂度约为：

```text
O(N × 384)
```

如果后续接入数十万条数据，建议逐步迁移到：

- PostgreSQL pgvector HNSW
- PostgreSQL pgvector IVFFlat
- FAISS
- Milvus
- Qdrant
- Elasticsearch kNN

现阶段先用 1,000～10,000 条数据验证业务闭环。

---

## 16. 当前尚未实现

以下能力属于后续规划，当前版本尚未实现：

- 38 万历史帖子完整接入
- 真实附近检索
- 经纬度与地理围栏
- 用户画像
- 帖子分类
- 情感分析
- 求助、问答、吐槽等意图识别
- 图检索与图模型
- 学习排序模型
- Spark CTR
- 线上 A/B Test
- 曝光、点击和解锁日志闭环

---

## 17. 近期开发顺序

```text
1. 确认真实数据源和字段
2. 增加 source 与 source_id
3. 编写 import_todo_data.py
4. 导入 1,000 条样本
5. 修复 embedding 持久化
6. 验证语义检索
7. 增加真实 Interaction 写入
8. 填充 Redis 在线数据
9. 扩大到 10,000 条
10. 再评估是否全量导入
```

---

## 18. 安全要求

禁止提交：

- 数据库密码
- Redis 密码
- 云服务器密码
- 对象存储 AK/SK
- API Key
- 用户隐私数据
- 真实线上数据文件
- 大体积模型缓存

建议 `.gitignore` 增加：

```text
.env
.env.*
*.pkl
*.joblib
*.log
data/
checkpoints/
models/
__pycache__/
```

---

## 19. 版本状态

```text
版本：TodoList CPython V1.0.0
状态：原型可运行
数据：真实数据尚未接入
模型：行为预测与检索均为 Demo
检索：尚未适配大规模数据
```

后续每次更新建议记录：

- 日期
- Commit
- 数据变化
- 模型变化
- 新增功能
- 验证结果
- 已知问题
