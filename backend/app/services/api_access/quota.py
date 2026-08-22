"""程序化 REST API（``/api/v1/*``）的双层限速与分层配额。

与 MCP inbound 同一套商业口径：分钟级突发桶防爬，检索调用再叠加分层
配额桶管商业权益（0045 会员体系）——匿名按 IP 走日配额、登录用户按
档位走日+月双层配额（日 pacing 防脉冲式爬取，30 天滚动窗管商业权益），
admin 豁免配额。Redis 故障 fail-open（可用性优先，
与 auth/MCP 限速同策略）。

配额桶字符串与 ``services/mcp/inbound/rate_limit`` 完全一致：MCP 与
REST 共享同一个配额池——用户 MCP 通道用了 1000 次，REST 通道就只剩
1000 次，杜绝双通道套利。突发桶独立（``api.search``，流量形状与
JSON-RPC 协议方法不同）。改任一侧的配额桶名/窗口/额度时必须同步
另一侧，契约测试（test_projects_api_access.SharedPoolContract）守护同值。
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
from backend.app.services.membership.tiers import (
    MEMBERSHIP_TIER_FREE,
    MEMBERSHIP_TIER_MEMBER,
    normalize_membership_tier,
)

logger = logging.getLogger(__name__)

API_RATE_LIMIT_WINDOW_SECONDS = 60
API_SEARCH_BUCKET = "api.search"
# 突发限额与 MCP tools/call 同口径（匿名 30/min、登录 120/min）
API_ANONYMOUS_SEARCH_LIMIT = 30
API_AUTHENTICATED_SEARCH_LIMIT = 120

# 配额桶与 MCP inbound 共享（同值即同池，勿漂移）：匿名日 30（IP 键）/
# 免费 60/天 + 1200/月 / 会员 400/天 + 8000/月（用户键）。月窗为 30 天
# 滚动固定窗口而非自然月——INCR+EXPIRE 原语无日历语义，滚动窗对脉冲式
# 用量更友好。登录档日配额是 pacing 层：杜绝单月额度被一次突发打光，
# 同时保证匿名持续用量（30×30=900/月）低于免费档月度总量，梯子不倒挂。
API_QUOTA_DAILY_BUCKET = "mcp.quota.daily"
API_QUOTA_MONTHLY_BUCKET = "mcp.quota.monthly"
API_QUOTA_DAILY_WINDOW_SECONDS = 86400
API_QUOTA_MONTHLY_WINDOW_SECONDS = 2592000
API_ANONYMOUS_DAILY_SEARCH_QUOTA = 30
API_FREE_DAILY_SEARCH_QUOTA = 60
API_FREE_MONTHLY_SEARCH_QUOTA = 1200
API_MEMBER_DAILY_SEARCH_QUOTA = 400
API_MEMBER_MONTHLY_SEARCH_QUOTA = 8000


class ApiQuotaExceededError(RuntimeError):
    """检索分层配额超限（区别于分钟级突发限速 RateLimitExceededError）。

    携带配额域信息供路由层投影：quota_scope（daily/monthly）、tier、
    limit、retry_after（超限键剩余 TTL 秒数，供 Retry-After 与客户端提示）、
    identity_kind（ip/user——匿名日配额与登录日配额同 scope 不同投影文案，
    按 IP 计的提示不能落在登录用户头上）。
    """

    def __init__(
        self,
        *,
        quota_scope: str,
        tier: str,
        limit: int,
        retry_after: int,
        identity_kind: str,
    ) -> None:
        super().__init__(f"api {quota_scope} quota exceeded for tier {tier}")
        self.quota_scope = quota_scope
        self.tier = tier
        self.limit = limit
        self.retry_after = retry_after
        self.identity_kind = identity_kind


def api_client_ip(request: Request) -> str:
    """Resolve the caller IP; X-Forwarded-For is honored only when the direct
    peer is a configured trusted reverse proxy (see core.client_ip)."""

    return client_ip_from_request(request)


async def enforce_api_search_rate_limit(
    request: Request,
    *,
    user_id: int,
    role: str = "user",
    membership_tier: str = MEMBERSHIP_TIER_FREE,
) -> None:
    """Consume one hit for this request; raise when over.

    两层限速：先分钟级突发桶（RateLimitExceededError → 429 慢下来重试），
    后分层配额桶（ApiQuotaExceededError → 429 升级档位）。被分钟桶 429 的
    请求走不到配额桶，不消耗配额。匿名按 IP、登录按 user id 键控。
    """

    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    if user_id > 0:
        identity = f"user:{user_id}"
        limit = API_AUTHENTICATED_SEARCH_LIMIT
    else:
        identity = f"ip:{api_client_ip(request)}"
        limit = API_ANONYMOUS_SEARCH_LIMIT
    try:
        await hit_rate_limit(
            redis_client,
            action=API_SEARCH_BUCKET,
            identity=identity,
            limit=limit,
            window_seconds=API_RATE_LIMIT_WINDOW_SECONDS,
        )
    except RateLimitExceededError:
        raise
    except Exception:
        logger.warning("API search rate limit skipped: redis unavailable", exc_info=True)

    if role == "admin":
        return
    await _enforce_search_quota(
        request,
        redis_client,
        user_id=user_id,
        membership_tier=membership_tier,
    )


async def _enforce_search_quota(
    request: Request,
    redis_client: Any,
    *,
    user_id: int,
    membership_tier: str,
) -> None:
    """Consume one search quota hit; raise ApiQuotaExceededError when over.

    匿名调用者按 IP 走日配额；登录用户按 user id 走日+月双层配额，档位以
    membership_tier 为准（未知档 fail-closed 按 free）。登录档先日桶后
    月桶：日桶是 pacing 层，被日桶拒绝的请求不再消耗月配额（防脉冲烧穿
    月度商业额度）。配额是商业软约束而非安全边界：固定窗口 + INCR 在
    并发下可能瞬时超 1，可接受。Redis 故障 fail-open（与分钟桶同口径）。
    """

    if user_id > 0:
        tier = normalize_membership_tier(membership_tier)
        identity = f"user:{user_id}"
        # 1. 日 pacing 桶（与匿名同桶不同键：mcp.quota.daily:user:<id>）
        daily_limit = (
            API_MEMBER_DAILY_SEARCH_QUOTA
            if tier == MEMBERSHIP_TIER_MEMBER
            else API_FREE_DAILY_SEARCH_QUOTA
        )
        await _hit_quota_bucket(
            redis_client,
            bucket=API_QUOTA_DAILY_BUCKET,
            identity=identity,
            window_seconds=API_QUOTA_DAILY_WINDOW_SECONDS,
            quota_scope="daily",
            tier=tier,
            limit=daily_limit,
            identity_kind="user",
        )
        # 2. 月度商业额度桶
        monthly_limit = (
            API_MEMBER_MONTHLY_SEARCH_QUOTA
            if tier == MEMBERSHIP_TIER_MEMBER
            else API_FREE_MONTHLY_SEARCH_QUOTA
        )
        await _hit_quota_bucket(
            redis_client,
            bucket=API_QUOTA_MONTHLY_BUCKET,
            identity=identity,
            window_seconds=API_QUOTA_MONTHLY_WINDOW_SECONDS,
            quota_scope="monthly",
            tier=tier,
            limit=monthly_limit,
            identity_kind="user",
        )
        return
    # 匿名没有账号档位，按免费档口径返回（日配额本身更紧）
    await _hit_quota_bucket(
        redis_client,
        bucket=API_QUOTA_DAILY_BUCKET,
        identity=f"ip:{api_client_ip(request)}",
        window_seconds=API_QUOTA_DAILY_WINDOW_SECONDS,
        quota_scope="daily",
        tier=MEMBERSHIP_TIER_FREE,
        limit=API_ANONYMOUS_DAILY_SEARCH_QUOTA,
        identity_kind="ip",
    )


async def _hit_quota_bucket(
    redis_client: Any,
    *,
    bucket: str,
    identity: str,
    window_seconds: int,
    quota_scope: str,
    tier: str,
    limit: int,
    identity_kind: str,
) -> None:
    """单桶命中+超限投影；Redis 故障 fail-open。"""

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
        raise ApiQuotaExceededError(
            quota_scope=quota_scope,
            tier=tier,
            limit=limit,
            retry_after=retry_after,
            identity_kind=identity_kind,
        )
    except Exception:
        logger.warning("API search quota check skipped: redis unavailable", exc_info=True)


async def _quota_retry_after(
    redis_client: Any, bucket: str, identity: str, *, fallback: int
) -> int:
    """Best-effort 读取超限键剩余 TTL 作 Retry-After；失败回退整窗秒数。"""

    try:
        ttl = await redis_client.ttl(f"{RATE_LIMIT_PREFIX}{bucket}:{identity}")
    except Exception:
        return fallback
    return ttl if isinstance(ttl, int) and ttl > 0 else fallback
