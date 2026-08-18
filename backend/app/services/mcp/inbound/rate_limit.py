"""Redis fixed-window rate limiting for the public inbound MCP endpoint.

Anonymous callers are limited per client IP, authenticated callers per user;
expensive ``tools/call`` traffic is bucketed separately from cheap protocol
methods. Redis outages fail open (availability over strictness), mirroring the
auth rate-limit policy.

两层正交限速：分钟级突发桶防爬（所有方法），``tools/call`` 再叠加分层
配额桶管商业权益（0045 会员体系）——匿名按日、登录按 30 天滚动窗，
档位来自 services/membership/tiers。先分钟桶后配额桶，被 429 的突发
请求不消耗配额；admin 豁免配额（运营排查不受商业约束）。
"""

from __future__ import annotations

import logging
from typing import Any

from starlette.requests import Request

from backend.app.core.client_ip import client_ip_from_request
from backend.app.services.auth.rate_limit import (
    RATE_LIMIT_PREFIX,
    RateLimitExceededError,
    hit_rate_limit,
)
from backend.app.services.mcp.inbound.application import McpProtocolResponse
from backend.app.services.mcp.inbound.context import McpSessionTransport
from backend.app.services.membership.tiers import (
    MEMBERSHIP_TIER_FREE,
    MEMBERSHIP_TIER_MEMBER,
    normalize_membership_tier,
)

logger = logging.getLogger(__name__)

MCP_RATE_LIMIT_WINDOW_SECONDS = 60
MCP_PROTOCOL_BUCKET = "mcp.protocol"
MCP_TOOL_CALL_BUCKET = "mcp.tool_call"
MCP_ANONYMOUS_PROTOCOL_LIMIT = 60
MCP_ANONYMOUS_TOOL_CALL_LIMIT = 30
MCP_AUTHENTICATED_PROTOCOL_LIMIT = 240
MCP_AUTHENTICATED_TOOL_CALL_LIMIT = 120
MCP_JSONRPC_RATE_LIMITED = -32000

# tools/call 分层配额：匿名日 100（IP 键）/ 免费月 2000 / 会员月 20000
# （用户键）。月窗为 30 天滚动固定窗口而非自然月——INCR+EXPIRE 原语
# 无日历语义，滚动窗对脉冲式用量更友好。
MCP_QUOTA_DAILY_BUCKET = "mcp.quota.daily"
MCP_QUOTA_MONTHLY_BUCKET = "mcp.quota.monthly"
MCP_QUOTA_DAILY_WINDOW_SECONDS = 86400
MCP_QUOTA_MONTHLY_WINDOW_SECONDS = 2592000
MCP_ANONYMOUS_DAILY_TOOL_CALL_QUOTA = 100
MCP_FREE_MONTHLY_TOOL_CALL_QUOTA = 2000
MCP_MEMBER_MONTHLY_TOOL_CALL_QUOTA = 20000


class McpQuotaExceededError(RuntimeError):
    """tools/call 分层配额超限（区别于分钟级突发限速 RateLimitExceededError）。

    携带配额域信息供路由层选择投影：quota_scope（daily/monthly）、tier、
    limit、retry_after（超限键剩余 TTL 秒数，供 Retry-After 与客户端提示）。
    """

    def __init__(
        self, *, quota_scope: str, tier: str, limit: int, retry_after: int
    ) -> None:
        super().__init__(f"mcp {quota_scope} quota exceeded for tier {tier}")
        self.quota_scope = quota_scope
        self.tier = tier
        self.limit = limit
        self.retry_after = retry_after


def mcp_client_ip(request: Request) -> str:
    """Resolve the caller IP; X-Forwarded-For is honored only when the direct
    peer is a configured trusted reverse proxy (see core.client_ip)."""

    return client_ip_from_request(request)


async def enforce_mcp_rate_limit(
    request: Request,
    *,
    method: str,
    user_id: int,
    role: str = "user",
    membership_tier: str = MEMBERSHIP_TIER_FREE,
) -> None:
    """Consume one hit for this request; raise when over.

    ``tools/call`` is bucketed separately because tool handlers may hit the
    database or the bounded GitHub API fallback. Anonymous callers are keyed
    by client IP with tighter limits; authenticated callers are keyed by user
    id. Redis unavailability fails open so the endpoint stays usable.

    两层限速：先分钟级突发桶（RateLimitExceededError → mcp_rate_limited_projection），
    后 tools/call 分层配额桶（McpQuotaExceededError → mcp_quota_exceeded_projection）。
    被分钟桶 429 的请求走不到配额桶，不消耗配额。
    """

    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    if method == "tools/call":
        bucket = MCP_TOOL_CALL_BUCKET
        anonymous_limit = MCP_ANONYMOUS_TOOL_CALL_LIMIT
        authenticated_limit = MCP_AUTHENTICATED_TOOL_CALL_LIMIT
    else:
        bucket = MCP_PROTOCOL_BUCKET
        anonymous_limit = MCP_ANONYMOUS_PROTOCOL_LIMIT
        authenticated_limit = MCP_AUTHENTICATED_PROTOCOL_LIMIT
    if user_id > 0:
        identity = f"user:{user_id}"
        limit = authenticated_limit
    else:
        identity = f"ip:{mcp_client_ip(request)}"
        limit = anonymous_limit
    try:
        await hit_rate_limit(
            redis_client,
            action=bucket,
            identity=identity,
            limit=limit,
            window_seconds=MCP_RATE_LIMIT_WINDOW_SECONDS,
        )
    except RateLimitExceededError:
        raise
    except Exception:
        logger.warning("MCP rate limit skipped: redis unavailable", exc_info=True)

    if method != "tools/call" or role == "admin":
        return
    await _enforce_tool_call_quota(
        request,
        redis_client,
        user_id=user_id,
        membership_tier=membership_tier,
    )


async def _enforce_tool_call_quota(
    request: Request,
    redis_client: Any,
    *,
    user_id: int,
    membership_tier: str,
) -> None:
    """Consume one tools/call quota hit; raise McpQuotaExceededError when over.

    匿名调用者按 IP 走日配额；登录用户按 user id 走月配额，档位以
    membership_tier 为准（未知档 fail-closed 按 free）。配额是商业软
    约束而非安全边界：固定窗口 + INCR 在并发下可能瞬时超 1，可接受。
    Redis 故障 fail-open（与分钟桶同口径）。
    """

    if user_id > 0:
        tier = normalize_membership_tier(membership_tier)
        bucket = MCP_QUOTA_MONTHLY_BUCKET
        identity = f"user:{user_id}"
        window_seconds = MCP_QUOTA_MONTHLY_WINDOW_SECONDS
        quota_scope = "monthly"
        limit = (
            MCP_MEMBER_MONTHLY_TOOL_CALL_QUOTA
            if tier == MEMBERSHIP_TIER_MEMBER
            else MCP_FREE_MONTHLY_TOOL_CALL_QUOTA
        )
    else:
        # 匿名没有账号档位，按免费档口径返回（日配额本身更紧）
        tier = MEMBERSHIP_TIER_FREE
        bucket = MCP_QUOTA_DAILY_BUCKET
        identity = f"ip:{mcp_client_ip(request)}"
        window_seconds = MCP_QUOTA_DAILY_WINDOW_SECONDS
        quota_scope = "daily"
        limit = MCP_ANONYMOUS_DAILY_TOOL_CALL_QUOTA
    try:
        await hit_rate_limit(
            redis_client,
            action=bucket,
            identity=identity,
            limit=limit,
            window_seconds=window_seconds,
        )
    except RateLimitExceededError:
        retry_after = await _quota_retry_after(
            redis_client, bucket, identity, fallback=window_seconds
        )
        raise McpQuotaExceededError(
            quota_scope=quota_scope,
            tier=tier,
            limit=limit,
            retry_after=retry_after,
        )
    except Exception:
        logger.warning("MCP quota check skipped: redis unavailable", exc_info=True)


async def _quota_retry_after(
    redis_client: Any, bucket: str, identity: str, *, fallback: int
) -> int:
    """Best-effort 读取超限键剩余 TTL 作 Retry-After；失败回退整窗秒数。"""

    try:
        ttl = await redis_client.ttl(f"{RATE_LIMIT_PREFIX}{bucket}:{identity}")
    except Exception:
        return fallback
    return ttl if isinstance(ttl, int) and ttl > 0 else fallback


def mcp_rate_limited_projection(request_id: Any) -> McpProtocolResponse:
    """HTTP 429 projection with a JSON-RPC error body for throttled requests."""

    return McpProtocolResponse(
        status_code=429,
        body={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": MCP_JSONRPC_RATE_LIMITED,
                "message": (
                    "Rate limit exceeded; slow down and retry after "
                    f"{MCP_RATE_LIMIT_WINDOW_SECONDS} seconds."
                ),
            },
        },
        headers={
            **McpSessionTransport().headers(),
            "Retry-After": str(MCP_RATE_LIMIT_WINDOW_SECONDS),
        },
    )


def mcp_quota_exceeded_projection(
    request_id: Any, exc: McpQuotaExceededError
) -> McpProtocolResponse:
    """HTTP 429 projection for tools/call 分层配额超限（区别于分钟级限速）。

    error.data 为加性扩展（quota_scope/tier/limit/retry_after），供客户端
    区分「慢下来重试」与「升级档位」；message 按档位给升级引导：
    匿名→领免费 key，免费→升会员，会员→告知窗口重置时间。
    """

    if exc.quota_scope == "daily":
        message = (
            f"Anonymous daily quota exceeded ({exc.limit} tool calls/day). "
            "Create a free account and MCP token for a higher monthly quota."
        )
    elif exc.tier == MEMBERSHIP_TIER_MEMBER:
        message = (
            f"Member monthly quota exceeded ({exc.limit} tool calls/month); "
            f"the window resets in {exc.retry_after} seconds."
        )
    else:
        message = (
            f"Free monthly quota exceeded ({exc.limit} tool calls/month). "
            "Upgrade to a membership for a higher quota."
        )
    return McpProtocolResponse(
        status_code=429,
        body={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": MCP_JSONRPC_RATE_LIMITED,
                "message": message,
                "data": {
                    "quota_scope": exc.quota_scope,
                    "tier": exc.tier,
                    "limit": exc.limit,
                    "retry_after": exc.retry_after,
                },
            },
        },
        headers={
            **McpSessionTransport().headers(),
            "Retry-After": str(exc.retry_after),
        },
    )
