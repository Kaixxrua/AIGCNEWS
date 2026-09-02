from __future__ import annotations

import logging

from fastapi_cache import FastAPICache
from redis.asyncio import Redis

from backend.app.core.config import settings
from backend.app.monitoring import live_stats_broadcaster

logger = logging.getLogger(__name__)


async def clear_dashboard_cache_safely() -> None:
    """Clear dashboard keys with a Redis client owned by this operation."""
    redis_client = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password or None,
        decode_responses=False,
    )
    try:
        raw_prefix = getattr(FastAPICache, "_prefix", "") or ""
        patterns = list(
            dict.fromkeys(
                [
                    "aigc-cache:dashboard:*",
                    f"{raw_prefix}dashboard:*",
                    "dashboard:*",
                    "*:dashboard:*",
                ]
            )
        )

        total_deleted = 0
        for pattern in patterns:
            keys = await redis_client.keys(pattern)
            if keys:
                await redis_client.delete(*keys)
                total_deleted += len(keys)
                logger.info(
                    "[Orchestrator] dashboard cache: pattern=%r 删除 %d keys。",
                    pattern,
                    len(keys),
                )

        if total_deleted == 0:
            logger.info("[Orchestrator] dashboard cache: 未找到可删除的 key（可能已过期）。")
        else:
            logger.info(
                "[Orchestrator] dashboard cache cleared，共删除 %d keys。",
                total_deleted,
            )
    finally:
        close_method = getattr(redis_client, "aclose", None)
        if close_method is not None:
            await close_method()
        else:
            await redis_client.close()
    # 动态计数常驻值随静态缓存一并换新：采集/ops 删除/X 运维共用本函数，
    # 在此统一通知 live-stats 广播器重算（未装配时 no-op，绝不抛出）。
    live_stats_broadcaster.notify_live_stats_changed("dashboard-cache-cleared")
