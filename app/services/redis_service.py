# app/services/redis_service.py
import redis.asyncio as redis
import os

# Redis address (localhost:6379)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

class RedisClient:
    def __init__(self):
        self.redis = None

    async def connect(self):
        """建立连接池"""
        self.redis = redis.from_url(
            REDIS_URL, 
            encoding="utf-8", 
            decode_responses=True #自动把字节转成字符串
        )
        try:
            await self.redis.ping()
            print(">>> [Redis] 连接成功！热度引擎已就绪。")
        except Exception as e:
            print(f">>> [Redis] 连接失败: {e}")

    async def close(self):
        """关闭连接"""
        if self.redis:
            await self.redis.close()
            
    async def get_client(self):
        """获取 Redis 客户端实例"""
        if self.redis is None:
            await self.connect()
        return self.redis

#单例对象
redis_manager = RedisClient()