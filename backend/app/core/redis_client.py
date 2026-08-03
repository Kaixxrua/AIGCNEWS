from __future__ import annotations

from redis.asyncio import Redis

from backend.app.core.config import settings


def create_redis_client(*, decode_responses: bool = False) -> Redis:
    """统一的应用异步 Redis 客户端工厂：连接参数只从 settings 读取。

    main.py lifespan 与 api/dependencies.py 此前各持有一份相同参数的连接
    构造；监控探针（monitoring/health.py）使用带超时的同步客户端，不在此列。
    """
    return Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password or None,
        decode_responses=decode_responses,
    )


async def close_redis_client(client: Redis) -> None:
    """兼容 redis-py 新旧版本的关闭入口（优先 aclose，回退 close）。"""
    close_method = getattr(client, "aclose", None)
    if close_method is not None:
        await close_method()
    else:
        await client.close()
