"""程序化 REST API（/api/v1/projects/*）限速与配额契约测试。

覆盖：分钟突发桶与分层配额双形态 429、匿名/免费/会员三档、admin 豁免、
Redis 故障 fail-open、真实 Bearer token 认证路径（无效 401）、以及与
MCP inbound 共享配额池的桶字符串契约（同值即同池，防双通道套利）。
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.app.api import routes_projects_api
from backend.app.api.dependencies import get_project_catalog_query_service
from backend.app.core import client_ip as client_ip_module
from backend.app.core.auth import OptionalMcpUser
from backend.app.services.api_access import quota as api_quota
from backend.app.services.api_access.quota import (
    API_ANONYMOUS_DAILY_SEARCH_QUOTA,
    API_ANONYMOUS_SEARCH_LIMIT,
    API_AUTHENTICATED_SEARCH_LIMIT,
    API_FREE_MONTHLY_SEARCH_QUOTA,
    API_MEMBER_MONTHLY_SEARCH_QUOTA,
    API_QUOTA_DAILY_BUCKET,
    API_QUOTA_DAILY_WINDOW_SECONDS,
    API_QUOTA_MONTHLY_BUCKET,
    API_QUOTA_MONTHLY_WINDOW_SECONDS,
    API_RATE_LIMIT_WINDOW_SECONDS,
    API_SEARCH_BUCKET,
    ApiQuotaExceededError,
    api_client_ip,
    enforce_api_search_rate_limit,
)
from backend.app.services.auth.rate_limit import RateLimitExceededError
from backend.app.services.mcp.inbound import rate_limit as mcp_rate_limit
from backend.tests.test_email_service_contracts import FakeRedis


def _request(
    redis,
    *,
    xff: str | None = None,
    client: tuple[str, int] = ("9.9.9.9", 5000),
) -> Request:
    headers = []
    if xff:
        headers.append((b"x-forwarded-for", xff.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/projects/search",
            "headers": headers,
            "client": client,
            "app": SimpleNamespace(state=SimpleNamespace(redis=redis)),
        }
    )


# 可信代理对端（回环）：XFF 才被采信
_TRUSTED_CLIENT = ("127.0.0.1", 5000)


class SharedPoolContract(unittest.TestCase):
    """REST 配额桶与 MCP inbound 同值——同值即同池，守护双通道共享语义。"""

    def test_quota_buckets_match_mcp_inbound(self) -> None:
        self.assertEqual(API_QUOTA_DAILY_BUCKET, mcp_rate_limit.MCP_QUOTA_DAILY_BUCKET)
        self.assertEqual(
            API_QUOTA_MONTHLY_BUCKET, mcp_rate_limit.MCP_QUOTA_MONTHLY_BUCKET
        )
        self.assertEqual(
            API_QUOTA_DAILY_WINDOW_SECONDS,
            mcp_rate_limit.MCP_QUOTA_DAILY_WINDOW_SECONDS,
        )
        self.assertEqual(
            API_QUOTA_MONTHLY_WINDOW_SECONDS,
            mcp_rate_limit.MCP_QUOTA_MONTHLY_WINDOW_SECONDS,
        )

    def test_quota_amounts_match_mcp_inbound(self) -> None:
        self.assertEqual(
            API_ANONYMOUS_DAILY_SEARCH_QUOTA,
            mcp_rate_limit.MCP_ANONYMOUS_DAILY_TOOL_CALL_QUOTA,
        )
        self.assertEqual(
            API_FREE_MONTHLY_SEARCH_QUOTA,
            mcp_rate_limit.MCP_FREE_MONTHLY_TOOL_CALL_QUOTA,
        )
        self.assertEqual(
            API_MEMBER_MONTHLY_SEARCH_QUOTA,
            mcp_rate_limit.MCP_MEMBER_MONTHLY_TOOL_CALL_QUOTA,
        )

    def test_burst_limits_match_mcp_tool_call(self) -> None:
        self.assertEqual(
            API_ANONYMOUS_SEARCH_LIMIT,
            mcp_rate_limit.MCP_ANONYMOUS_TOOL_CALL_LIMIT,
        )
        self.assertEqual(
            API_AUTHENTICATED_SEARCH_LIMIT,
            mcp_rate_limit.MCP_AUTHENTICATED_TOOL_CALL_LIMIT,
        )
        self.assertEqual(
            API_RATE_LIMIT_WINDOW_SECONDS,
            mcp_rate_limit.MCP_RATE_LIMIT_WINDOW_SECONDS,
        )


class ClientIpTests(unittest.TestCase):
    def test_trusted_peer_prefers_first_forwarded_for_hop(self) -> None:
        request = _request(FakeRedis(), xff="1.2.3.4, 10.0.0.1", client=_TRUSTED_CLIENT)
        self.assertEqual(api_client_ip(request), "1.2.3.4")

    def test_untrusted_peer_ignores_forwarded_for(self) -> None:
        request = _request(FakeRedis(), xff="1.2.3.4")
        self.assertEqual(api_client_ip(request), "9.9.9.9")


class EnforceRateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_anonymous_identity_uses_ip_and_search_bucket(self) -> None:
        redis = FakeRedis()
        request = _request(redis, xff="1.2.3.4", client=_TRUSTED_CLIENT)
        await enforce_api_search_rate_limit(request, user_id=0)
        key = f"ratelimit:{API_SEARCH_BUCKET}:ip:1.2.3.4"
        self.assertEqual(redis.values[key], 1)
        self.assertEqual(redis.expirations[key], API_RATE_LIMIT_WINDOW_SECONDS)

    async def test_authenticated_identity_uses_user_id(self) -> None:
        redis = FakeRedis()
        request = _request(redis, xff="1.2.3.4", client=_TRUSTED_CLIENT)
        await enforce_api_search_rate_limit(request, user_id=42)
        self.assertEqual(redis.values[f"ratelimit:{API_SEARCH_BUCKET}:user:42"], 1)

    async def test_anonymous_burst_limit_is_enforced(self) -> None:
        redis = FakeRedis()
        request = _request(redis, xff="1.2.3.4", client=_TRUSTED_CLIENT)
        with patch.object(api_quota, "API_ANONYMOUS_SEARCH_LIMIT", 2):
            await enforce_api_search_rate_limit(request, user_id=0)
            await enforce_api_search_rate_limit(request, user_id=0)
            with self.assertRaises(RateLimitExceededError):
                await enforce_api_search_rate_limit(request, user_id=0)

    async def test_fail_open_when_redis_missing_or_broken(self) -> None:
        request = _request(None, xff="1.2.3.4")
        await enforce_api_search_rate_limit(request, user_id=0)

        class BrokenRedis:
            async def incr(self, key: str) -> int:
                raise ConnectionError("redis down")

        request = _request(BrokenRedis(), xff="1.2.3.4")
        await enforce_api_search_rate_limit(request, user_id=0)


class QuotaEnforcementTests(unittest.IsolatedAsyncioTestCase):
    """分层配额：匿名日 100 / 免费月 2000 / 会员月 20000（与 MCP 同池）。"""

    async def test_anonymous_call_consumes_daily_ip_quota_in_shared_bucket(self) -> None:
        redis = FakeRedis()
        request = _request(redis, xff="1.2.3.4", client=_TRUSTED_CLIENT)
        await enforce_api_search_rate_limit(request, user_id=0)
        # 键名即 MCP 日配额桶：REST 调用直接消耗 MCP 通道可见的同一池
        key = "ratelimit:mcp.quota.daily:ip:1.2.3.4"
        self.assertEqual(redis.values[key], 1)
        self.assertEqual(redis.expirations[key], API_QUOTA_DAILY_WINDOW_SECONDS)

    async def test_authenticated_call_consumes_monthly_user_quota(self) -> None:
        redis = FakeRedis()
        request = _request(redis, xff="1.2.3.4", client=_TRUSTED_CLIENT)
        await enforce_api_search_rate_limit(request, user_id=42)
        key = "ratelimit:mcp.quota.monthly:user:42"
        self.assertEqual(redis.values[key], 1)
        self.assertEqual(redis.expirations[key], API_QUOTA_MONTHLY_WINDOW_SECONDS)
        self.assertNotIn("ratelimit:mcp.quota.daily:ip:1.2.3.4", redis.values)

    async def test_anonymous_daily_quota_boundary(self) -> None:
        redis = FakeRedis()
        request = _request(redis, xff="1.2.3.4", client=_TRUSTED_CLIENT)
        with patch.object(api_quota, "API_ANONYMOUS_DAILY_SEARCH_QUOTA", 2):
            await enforce_api_search_rate_limit(request, user_id=0)
            await enforce_api_search_rate_limit(request, user_id=0)
            with self.assertRaises(ApiQuotaExceededError) as caught:
                await enforce_api_search_rate_limit(request, user_id=0)
        exc = caught.exception
        self.assertEqual(exc.quota_scope, "daily")
        self.assertEqual(exc.tier, "free")
        self.assertEqual(exc.limit, 2)
        self.assertEqual(exc.retry_after, API_QUOTA_DAILY_WINDOW_SECONDS)

    async def test_free_monthly_quota_boundary(self) -> None:
        redis = FakeRedis()
        request = _request(redis, client=_TRUSTED_CLIENT)
        with patch.object(api_quota, "API_FREE_MONTHLY_SEARCH_QUOTA", 2):
            for _ in range(2):
                await enforce_api_search_rate_limit(request, user_id=7)
            with self.assertRaises(ApiQuotaExceededError) as caught:
                await enforce_api_search_rate_limit(request, user_id=7)
        exc = caught.exception
        self.assertEqual(exc.quota_scope, "monthly")
        self.assertEqual(exc.tier, "free")
        self.assertEqual(exc.retry_after, API_QUOTA_MONTHLY_WINDOW_SECONDS)

    async def test_member_tier_uses_member_quota(self) -> None:
        redis = FakeRedis()
        request = _request(redis, client=_TRUSTED_CLIENT)
        with patch.object(api_quota, "API_MEMBER_MONTHLY_SEARCH_QUOTA", 1):
            await enforce_api_search_rate_limit(
                request, user_id=7, membership_tier="member"
            )
            with self.assertRaises(ApiQuotaExceededError) as caught:
                await enforce_api_search_rate_limit(
                    request, user_id=7, membership_tier="member"
                )
        self.assertEqual(caught.exception.tier, "member")

    async def test_unknown_tier_fails_closed_to_free_quota(self) -> None:
        redis = FakeRedis()
        request = _request(redis, client=_TRUSTED_CLIENT)
        with patch.object(api_quota, "API_FREE_MONTHLY_SEARCH_QUOTA", 1):
            await enforce_api_search_rate_limit(
                request, user_id=7, membership_tier="vip"
            )
            with self.assertRaises(ApiQuotaExceededError) as caught:
                await enforce_api_search_rate_limit(
                    request, user_id=7, membership_tier="vip"
                )
        self.assertEqual(caught.exception.tier, "free")

    async def test_admin_role_is_exempt_from_quota_but_not_burst(self) -> None:
        redis = FakeRedis()
        request = _request(redis, xff="1.2.3.4", client=_TRUSTED_CLIENT)
        for _ in range(3):
            await enforce_api_search_rate_limit(request, user_id=1, role="admin")
        self.assertFalse(
            any("quota" in key for key in redis.values),
            f"admin 不应消耗配额桶: {redis.values}",
        )
        # 突发桶仍然计数（防爬对 admin 同样生效）
        self.assertEqual(redis.values[f"ratelimit:{API_SEARCH_BUCKET}:user:1"], 3)

    async def test_minute_bucket_throttle_does_not_consume_quota(self) -> None:
        redis = FakeRedis()
        request = _request(redis, xff="1.2.3.4", client=_TRUSTED_CLIENT)
        with patch.object(api_quota, "API_ANONYMOUS_SEARCH_LIMIT", 1):
            await enforce_api_search_rate_limit(request, user_id=0)
            with self.assertRaises(RateLimitExceededError):
                await enforce_api_search_rate_limit(request, user_id=0)
        # 第二次被分钟桶 429，走不到配额桶
        self.assertEqual(redis.values["ratelimit:mcp.quota.daily:ip:1.2.3.4"], 1)

    async def test_quota_fails_open_when_redis_missing_or_broken(self) -> None:
        request = _request(None, xff="1.2.3.4", client=_TRUSTED_CLIENT)
        await enforce_api_search_rate_limit(request, user_id=0)

        class BrokenRedis:
            async def incr(self, key: str) -> int:
                raise ConnectionError("redis down")

        request = _request(BrokenRedis(), xff="1.2.3.4", client=_TRUSTED_CLIENT)
        await enforce_api_search_rate_limit(request, user_id=0)


class _StubCatalog:
    min_stars = 500

    async def list_public_projects(self, **kwargs):
        return SimpleNamespace(
            result={
                "items": [],
                "total": 0,
                "page": kwargs["page"],
                "page_size": kwargs["page_size"],
            },
            effective_sort="relevance",
        )

    async def get_public_categories(self):
        return {"items": [], "total": 0, "today_count": 0, "recommended_count": 0}


class _StubTokenRepository:
    """get_user_by_mcp_token_hash 的最小替身：按配置返回用户或 None。"""

    def __init__(self, user):
        self._user = user

    def get_user_by_mcp_token_hash(self, token_hash: str):
        return self._user


class _StubRepositories:
    def __init__(self, user):
        self.mcp_access_tokens = _StubTokenRepository(user)


class ProjectsApiRouteContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = FakeRedis()
        app = FastAPI()
        app.include_router(routes_projects_api.router, prefix="/api")
        app.state.redis = self.redis
        app.dependency_overrides[get_project_catalog_query_service] = (
            lambda: _StubCatalog()
        )
        self.app = app
        self.client = TestClient(app)
        # TestClient 直连对端默认不可信；显式信任等效生产边缘回源，
        # XFF 用例才能按真实客户端 IP 分桶。
        self._trust_patcher = patch.object(
            client_ip_module, "is_trusted_proxy", return_value=True
        )
        self._trust_patcher.start()
        self.addCleanup(self._trust_patcher.stop)

    def test_search_envelope_matches_website_shape(self) -> None:
        response = self.client.get(
            "/api/v1/projects/search",
            params={"q": "rag", "page_size": 8},
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        for key in (
            "items",
            "total",
            "page",
            "page_size",
            "has_next",
            "min_stars",
            "scope",
            "category",
            "subcategory",
            "q",
            "sort",
            "source",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["source"], "github")
        self.assertEqual(payload["min_stars"], 500)
        self.assertEqual(payload["q"], "rag")
        self.assertEqual(payload["page_size"], 8)
        self.assertFalse(payload["has_next"])

    def test_categories_envelope_includes_scope_items(self) -> None:
        response = self.client.get(
            "/api/v1/projects/categories",
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["min_stars"], 500)
        slugs = [item["slug"] for item in payload["items"]]
        self.assertEqual(slugs, ["all", "recommended", "today"])

    def test_non_bearer_authorization_rejected_401(self) -> None:
        response = self.client.get(
            "/api/v1/projects/search",
            headers={"Authorization": "Token abc"},
        )
        self.assertEqual(response.status_code, 401)

    def test_invalid_bearer_token_rejected_401(self) -> None:
        self.app.state.application_repositories = _StubRepositories(None)
        response = self.client.get(
            "/api/v1/projects/search",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        self.assertEqual(response.status_code, 401)

    def test_valid_token_uses_user_scoped_shared_pool(self) -> None:
        self.app.state.application_repositories = _StubRepositories(
            {
                "user_id": 42,
                "role": "user",
                "membership_tier": "free",
                "scopes": ["read"],
            }
        )
        response = self.client.get(
            "/api/v1/projects/search",
            headers={"Authorization": "Bearer real-token"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"ratelimit:{API_SEARCH_BUCKET}:user:42", self.redis.values)
        self.assertIn("ratelimit:mcp.quota.monthly:user:42", self.redis.values)

    def test_burst_limit_returns_429_without_quota_fields(self) -> None:
        with patch.object(api_quota, "API_ANONYMOUS_SEARCH_LIMIT", 2):
            for _ in range(2):
                response = self.client.get(
                    "/api/v1/projects/search",
                    headers={"X-Forwarded-For": "1.2.3.4"},
                )
                self.assertEqual(response.status_code, 200)
            throttled = self.client.get(
                "/api/v1/projects/search",
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
        self.assertEqual(throttled.status_code, 429)
        self.assertEqual(
            throttled.headers["Retry-After"], str(API_RATE_LIMIT_WINDOW_SECONDS)
        )
        payload = throttled.json()
        self.assertEqual(payload["error"], "rate_limited")
        self.assertNotIn("quota_scope", payload)

    def test_anonymous_daily_quota_exceeded_returns_quota_projection(self) -> None:
        with patch.object(api_quota, "API_ANONYMOUS_DAILY_SEARCH_QUOTA", 1):
            first = self.client.get(
                "/api/v1/projects/search",
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            self.assertEqual(first.status_code, 200)
            throttled = self.client.get(
                "/api/v1/projects/search",
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
        self.assertEqual(throttled.status_code, 429)
        self.assertEqual(
            throttled.headers["Retry-After"], str(API_QUOTA_DAILY_WINDOW_SECONDS)
        )
        payload = throttled.json()
        self.assertEqual(payload["error"], "quota_exceeded")
        self.assertEqual(payload["quota_scope"], "daily")
        self.assertEqual(payload["tier"], "free")
        self.assertEqual(payload["limit"], 1)
        self.assertIn("aigcnews.cn/mcp", payload["detail"])
        self.assertIn("aigcnews.cn/membership", payload["detail"])

    def test_free_user_monthly_quota_exceeded_guides_to_membership(self) -> None:
        self.app.dependency_overrides[OptionalMcpUser] = lambda: {
            "user_id": 42,
            "scopes": frozenset(),
            "role": "user",
            "membership_tier": "free",
        }
        with patch.object(api_quota, "API_FREE_MONTHLY_SEARCH_QUOTA", 1):
            self.client.get("/api/v1/projects/search")
            throttled = self.client.get("/api/v1/projects/search")
        self.assertEqual(throttled.status_code, 429)
        payload = throttled.json()
        self.assertEqual(payload["quota_scope"], "monthly")
        self.assertEqual(payload["tier"], "free")
        self.assertIn("aigcnews.cn/membership", payload["detail"])
        self.assertIn("VIP", payload["detail"])

    def test_member_user_gets_member_quota(self) -> None:
        self.app.dependency_overrides[OptionalMcpUser] = lambda: {
            "user_id": 42,
            "scopes": frozenset(),
            "role": "user",
            "membership_tier": "member",
        }
        # 免费档 1 次即超限的窗口里，会员档（打补丁为 3）仍可继续调用
        with patch.object(api_quota, "API_FREE_MONTHLY_SEARCH_QUOTA", 1):
            with patch.object(api_quota, "API_MEMBER_MONTHLY_SEARCH_QUOTA", 3):
                for _ in range(3):
                    response = self.client.get("/api/v1/projects/search")
                    self.assertEqual(response.status_code, 200)
                throttled = self.client.get("/api/v1/projects/search")
        self.assertEqual(throttled.status_code, 429)
        payload = throttled.json()
        self.assertEqual(payload["tier"], "member")
        self.assertEqual(payload["limit"], 3)
        self.assertIn("VIP monthly quota", payload["detail"])
        self.assertIn("window resets", payload["detail"])

    def test_admin_user_skips_quota_entirely(self) -> None:
        self.app.dependency_overrides[OptionalMcpUser] = lambda: {
            "user_id": 1,
            "scopes": frozenset(),
            "role": "admin",
            "membership_tier": "free",
        }
        with patch.object(api_quota, "API_FREE_MONTHLY_SEARCH_QUOTA", 1):
            for _ in range(3):
                response = self.client.get("/api/v1/projects/search")
                self.assertEqual(response.status_code, 200)
        self.assertFalse(any("quota" in key for key in self.redis.values))

    def test_distinct_ips_have_isolated_quotas(self) -> None:
        with patch.object(api_quota, "API_ANONYMOUS_SEARCH_LIMIT", 1):
            first = self.client.get(
                "/api/v1/projects/search",
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            self.assertEqual(first.status_code, 200)
            other = self.client.get(
                "/api/v1/projects/search",
                headers={"X-Forwarded-For": "5.6.7.8"},
            )
            self.assertEqual(other.status_code, 200)

    def test_spoofed_xff_from_untrusted_peer_shares_quota(self) -> None:
        # 直连对端不可信时忽略 XFF：不同伪造值归并同一对端桶，无法借
        # 换头拆分配额（等效攻击者绕过边缘直连后端的场景）。
        self._trust_patcher.stop()
        with patch.object(api_quota, "API_ANONYMOUS_SEARCH_LIMIT", 1):
            first = self.client.get(
                "/api/v1/projects/search",
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            self.assertEqual(first.status_code, 200)
            throttled = self.client.get(
                "/api/v1/projects/search",
                headers={"X-Forwarded-For": "5.6.7.8"},
            )
            self.assertEqual(throttled.status_code, 429)

    def test_minute_throttled_requests_do_not_consume_quota(self) -> None:
        with patch.object(api_quota, "API_ANONYMOUS_SEARCH_LIMIT", 1):
            first = self.client.get(
                "/api/v1/projects/search",
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            self.assertEqual(first.status_code, 200)
            throttled = self.client.get(
                "/api/v1/projects/search",
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            self.assertEqual(throttled.status_code, 429)
            self.assertEqual(throttled.json()["error"], "rate_limited")
        self.assertEqual(
            self.redis.values["ratelimit:mcp.quota.daily:ip:1.2.3.4"], 1
        )

    def test_categories_endpoint_shares_the_same_enforcement(self) -> None:
        with patch.object(api_quota, "API_ANONYMOUS_SEARCH_LIMIT", 1):
            first = self.client.get(
                "/api/v1/projects/search",
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            self.assertEqual(first.status_code, 200)
            throttled = self.client.get(
                "/api/v1/projects/categories",
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            self.assertEqual(throttled.status_code, 429)

    def test_fail_open_when_redis_unavailable(self) -> None:
        class BrokenRedis:
            async def incr(self, key: str) -> int:
                raise ConnectionError("redis down")

        self.app.state.redis = BrokenRedis()
        with patch.object(api_quota, "API_ANONYMOUS_SEARCH_LIMIT", 1):
            for _ in range(3):
                response = self.client.get(
                    "/api/v1/projects/search",
                    headers={"X-Forwarded-For": "1.2.3.4"},
                )
                self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
