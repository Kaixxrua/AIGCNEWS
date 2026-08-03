"""Redis 固定窗口速率限制，用于认证相关敏感端点。"""

from __future__ import annotations

RATE_LIMIT_PREFIX = "ratelimit:"


class RateLimitExceededError(RuntimeError):
    """Raised when an action exceeds its configured rate limit."""


async def hit_rate_limit(
    redis_client,
    *,
    action: str,
    identity: str,
    limit: int,
    window_seconds: int,
) -> int:
    """为 (action, identity) 记录一次命中并返回窗口内累计次数。

    采用固定窗口：首次命中时设置 TTL，窗口内次数超过 limit 时抛出
    RateLimitExceededError。键随 TTL 自然过期，无需清理任务。
    """
    key = f"{RATE_LIMIT_PREFIX}{action}:{identity}"
    count = await redis_client.incr(key)
    if count == 1:
        await redis_client.expire(key, window_seconds)
    if count > limit:
        raise RateLimitExceededError(action)
    return count
