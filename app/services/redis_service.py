import os
import redis.asyncio as redis
import json
import time

class RedisService:
    def __init__(self):
        # Local development defaults to localhost. Remote environments
        # should provide REDIS_URL through .env or process variables.
        self.redis_url = os.getenv(
            "REDIS_URL",
            "redis://127.0.0.1:6379/0",
        )
        self.r = redis.from_url(
            self.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        
        # === Keys define ===
        self.TRENDING_KEY = "todo_trending"     # Target 3: 全网热度榜
        self.EXCHANGE_KEY = "ad_exchange_book"  # Target 4: 竞价池
        self.WALLET_PREFIX = "user_wallet:"     # Target 4: 用户钱包
        self.PENDING_KEY = "ad_audit_queue"     # 待审核队列 (List)
        self.ACTIVE_ADS_KEY = "ad_active_pool"  # 已审核通过的广告池 (ZSet)

    async def connect(self):
        """
        启动时测试连接 (Lifespan 调用)
        """
        try:
            await self.r.ping()
            print(">>> [Redis] Connected successfully.")
        except Exception as e:
            print(f"❌ [Redis] Connection failed: {e}")

    async def close(self):
        await self.r.aclose()
        print(">>> [Redis] Connection closed.")

    # ==========================================
    # Target 3: Trending
    # ==========================================
    
    async def search_add(self, keyword: str):
        """
        [新增] 增加关键词热度 (Hot +1)
        使用 ZINCRBY: 如果存在就+1，不存在就创建并设为1
        """
        if not keyword:
            return
        # 对应 endpoints.py 里的 await redis_client.search_add(tag)
        await self.r.zincrby(self.TRENDING_KEY, 1, keyword)

    async def get_trending(self, top_k: int = 10):
        """
        获取热度排行榜
        """
        # ZREVRANGE: 分数从高到低
        items = await self.r.zrevrange(self.TRENDING_KEY, 0, top_k - 1, withscores=True)
        
        # 转换格式给前端
        results = []
        # items 是列表: [('吃饭', 5.0), ('睡觉', 3.0)]
        for i, (content, score) in enumerate(items):
            results.append({
                "rank": i + 1,
                "content": content,
                "hot_index": int(score)
            })
        return {"list": results}

    # ==========================================
    # Target 4: MAB (Wallet)
    # ==========================================

    async def get_balance(self, user_id: str) -> int:
        """查询余额"""
        balance = await self.r.get(f"{self.WALLET_PREFIX}{user_id}")
        return int(balance) if balance else 0

    async def add_mab(self, user_id: str, amount: int):
        """充值/挖矿"""
        return await self.r.incrby(f"{self.WALLET_PREFIX}{user_id}", amount)

    async def deduct_mab(self, user_id: str, amount: int) -> bool:
        """扣费 (原子操作)"""
        key = f"{self.WALLET_PREFIX}{user_id}"
        # 注意！！：这里有一个并发小瑕疵，严格来说应该用 Lua 脚本，但demo够用了
        current = await self.get_balance(user_id)
        if current >= amount:
            await self.r.decrby(key, amount)
            return True
        return False

    # ==========================================
    # Target 4: Ad-Exchange 竞价引擎
    # ==========================================

    async def place_bid(self, task_id: int, content: str, bid_price: int, user_id: str):
        """发布竞价单"""
        payload = json.dumps({
            "task_id": task_id,
            "content": content,
            "bid": bid_price,
            "sponsor": user_id,
            "ts": time.time()
        })
        # ZSET: Score=价格, Value=单子详情
        await self.r.zadd(self.EXCHANGE_KEY, {payload: bid_price})

    async def get_order_book(self, top_k: int = 10):
        """获取竞价大厅列表"""
        items = await self.r.zrevrange(self.EXCHANGE_KEY, 0, top_k - 1, withscores=True)
        results = []
        for payload_str, score in items:
            try:
                data = json.loads(payload_str)
                results.append(data)
            except:
                continue
        return results

    async def clear_exchange(self):
        """清空市场 (调试用)"""
        await self.r.delete(self.EXCHANGE_KEY)

    async def settle_order(self, raw_payload: str, worker_id: str) -> bool:
        """
        [结算] 撮合成功：
        1. 从竞价池移除订单 (ZREM)
        2. 给接单人(Worker) 转账/发奖励 (INCRBY)
        """
        try:
            # 1. 解析订单看看值多少钱
            data = json.loads(raw_payload)
            bid_amount = int(data.get("bid", 0))
            sponsor_id = data.get("sponsor")
            
            # 不能自己接自己的单刷钱
            if sponsor_id == worker_id:
                return False

            # 2. 从 ZSET 中移除该订单 (原子操作)
            # zrem 返回被移除元素的数量，如果为0说明已经被别人抢了
            removed_count = await self.r.zrem(self.EXCHANGE_KEY, raw_payload)
            
            if removed_count > 0:
                # 3. 只有真正抢到了(移除成功)，才给接单人加钱
                await self.add_mab(worker_id, bid_amount)
                print(f"💰 [结算] 交易成功! {sponsor_id} -> {worker_id} (金额: {bid_amount})")
                return True
            else:
                print("⚠️ [结算] 订单不存在或已被抢走")
                return False
                
        except Exception as e:
            print(f"❌ [结算] 异常: {e}")
            return False

    async def get_order_book_raw(self, top_k: int = 20):
        """
        [前端专用] 获取带原始 Payload 的列表
        需要原始 JSON 字符串来作为删除时的 Key
        """
        items = await self.r.zrevrange(self.EXCHANGE_KEY, 0, top_k - 1, withscores=True)
        results = []
        for payload_str, score in items:
            try:
                data = json.loads(payload_str)
                # 把原始字符串塞入，方便前端传回来
                data["_raw"] = payload_str 
                results.append(data)
            except:
                continue
        return results
    
    def get_client(self):
        """
        [Fix] 暴露原始连接 self.r, 防止外部调用 get_client() 报错
        """
        return self.r
    # ==========================================
    # Target 5: 审核 (Audit)
    # ==========================================

    async def submit_for_audit(self, task_id: int, content: str, bid_price: int, user_id: str):
        """
        提交广告到审核队列 (将原来的 place_bid 直接上架)
        """
        payload = json.dumps({
            "task_id": task_id,
            "content": content,
            "bid": bid_price,
            "sponsor": user_id,
            "ts": time.time(),
            "status": "pending"
        })
        # push to right side of the list
        await self.r.rpush(self.PENDING_KEY, payload)
        print(f"🛡️ [Audit] 广告已提交审核: {content}")

    async def get_pending_ads(self):
        """获取所有待审核广告"""
        # LRANGE 0 -1 获取所有
        items = await self.r.lrange(self.PENDING_KEY, 0, -1)
        return [json.loads(i) for i in items]

    async def approve_ad(self, raw_payload: str):
        """
        [NEW] 管理员批准广告
        1. 从审核队列移除
        2. 加入活跃广告池 (ZSet, score=bid)
        """
        # 1. 移除 (LREM)
        await self.r.lrem(self.PENDING_KEY, 0, raw_payload)
        
        # 2. 修改状态并上架
        data = json.loads(raw_payload)
        data["status"] = "active"
        bid = data.get("bid", 0)
        
        # 存入 ACTIVE 池 (原来的 board 也可以读这个，或专门用于智能推荐)
        # 为了演示 Target 5，存入一个新的池子，专门给 Todo 列表混入用
        new_payload = json.dumps(data)
        await self.r.zadd(self.ACTIVE_ADS_KEY, {new_payload: bid})
        
        # 同时同步到原来的 Market Key (为了兼容 Target 4 的市场列表)
        await self.r.zadd(self.EXCHANGE_KEY, {new_payload: bid})
        
        print(f"✅ [Audit] 广告已批准上架: {data.get('content')}")
        return True

    async def reject_ad(self, raw_payload: str):
        """拒绝广告 (退款逻辑暂略，先只做删除)"""
        await self.r.lrem(self.PENDING_KEY, 0, raw_payload)
        # 实际业务中这里应该调用 add_mab 退钱给 sponsor
        print(f"❌ [Audit] 广告已拒绝")

# 全局 Redis 客户端实例
redis_client = RedisService()