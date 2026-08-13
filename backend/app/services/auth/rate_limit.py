"""Redis 固定窗口速率限制，用于认证相关敏感端点。"""

from __future__ import annotations

RATE_LIMIT_PREFIX = "ratelimit:"
LOGIN_FAILURE_PREFIX = "loginfail:"


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


async def get_login_failure_count(redis_client, *, email: str) -> int:
    """读取账号窗口内累计登录失败次数（键不存在视为 0）。"""
    value = await redis_client.get(f"{LOGIN_FAILURE_PREFIX}{email}")
    if value is None:
        return 0
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return int(value)


async def record_login_failure(
    redis_client,
    *,
    email: str,
    window_seconds: int,
) -> int:
    """为账号记录一次登录失败并返回窗口内累计失败数（固定窗口 TTL）。"""
    key = f"{LOGIN_FAILURE_PREFIX}{email}"
    count = await redis_client.incr(key)
    if count == 1:
        await redis_client.expire(key, window_seconds)
    return count


async def clear_login_failures(redis_client, *, email: str) -> None:
    """登录成功后清零账号失败计数。"""
    await redis_client.delete(f"{LOGIN_FAILURE_PREFIX}{email}")
