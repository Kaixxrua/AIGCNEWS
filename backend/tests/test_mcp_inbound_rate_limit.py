"""公共 inbound MCP 端点限流契约测试。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.app.api import routes_mcp
from backend.app.api.dependencies import (
    get_application_repositories,
    get_briefing_repository,
    get_project_search_runtime,
)
from backend.app.core import client_ip as client_ip_module
from backend.app.core.auth import OptionalMcpUser
from backend.app.services.auth.rate_limit import RateLimitExceededError
from backend.app.services.mcp.inbound import rate_limit as mcp_rate_limit
from backend.app.services.mcp.inbound.rate_limit import (
    MCP_JSONRPC_RATE_LIMITED,
    MCP_RATE_LIMIT_WINDOW_SECONDS,
    enforce_mcp_rate_limit,
    mcp_client_ip,
    mcp_rate_limited_projection,
)
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
            "method": "POST",
            "path": "/api/mcp",
            "headers": headers,
            "client": client,
            "app": SimpleNamespace(state=SimpleNamespace(redis=redis)),
        }
    )


# 可信代理对端（回环）：XFF 才被采信
_TRUSTED_CLIENT = ("127.0.0.1", 5000)


class ClientIpTests(unittest.TestCase):
    def test_trusted_peer_prefers_first_forwarded_for_hop(self) -> None:
        request = _request(FakeRedis(), xff="1.2.3.4, 10.0.0.1", client=_TRUSTED_CLIENT)
        self.assertEqual(mcp_client_ip(request), "1.2.3.4")

    def test_untrusted_peer_ignores_forwarded_for(self) -> None:
        request = _request(FakeRedis(), xff="1.2.3.4")
        self.assertEqual(mcp_client_ip(request), "9.9.9.9")

    def test_falls_back_to_connection_client(self) -> None:
        request = _request(FakeRedis())
        self.assertEqual(mcp_client_ip(request), "9.9.9.9")


class EnforceRateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_anonymous_identity_uses_ip_and_protocol_bucket(self) -> None:
        redis = FakeRedis()
        request = _request(redis, xff="1.2.3.4", client=_TRUSTED_CLIENT)
        await enforce_mcp_rate_limit(request, method="tools/list", user_id=0)
        self.assertEqual(redis.values["ratelimit:mcp.protocol:ip:1.2.3.4"], 1)
        self.assertEqual(
            redis.expirations["ratelimit:mcp.protocol:ip:1.2.3.4"],
            MCP_RATE_LIMIT_WINDOW_SECONDS,
        )

    async def test_tool_call_uses_dedicated_bucket(self) -> None:
        redis = FakeRedis()
        request = _request(redis, xff="1.2.3.4", client=_TRUSTED_CLIENT)
        await enforce_mcp_rate_limit(request, method="tools/call", user_id=0)
        self.assertEqual(redis.values["ratelimit:mcp.tool_call:ip:1.2.3.4"], 1)
        self.assertNotIn("ratelimit:mcp.protocol:ip:1.2.3.4", redis.values)

    async def test_authenticated_identity_uses_user_id(self) -> None:
        redis = FakeRedis()
        request = _request(redis, xff="1.2.3.4", client=_TRUSTED_CLIENT)
        await enforce_mcp_rate_limit(request, method="tools/call", user_id=42)
        self.assertEqual(redis.values["ratelimit:mcp.tool_call:user:42"], 1)

    async def test_anonymous_tool_call_limit_is_enforced(self) -> None:
        redis = FakeRedis()
        request = _request(redis, xff="1.2.3.4", client=_TRUSTED_CLIENT)
        with patch.object(mcp_rate_limit, "MCP_ANONYMOUS_TOOL_CALL_LIMIT", 2):
            await enforce_mcp_rate_limit(request, method="tools/call", user_id=0)
            await enforce_mcp_rate_limit(request, method="tools/call", user_id=0)
            with self.assertRaises(RateLimitExceededError):
                await enforce_mcp_rate_limit(request, method="tools/call", user_id=0)

    async def test_authenticated_limit_is_higher_than_anonymous(self) -> None:
        self.assertGreater(
            mcp_rate_limit.MCP_AUTHENTICATED_TOOL_CALL_LIMIT,
            mcp_rate_limit.MCP_ANONYMOUS_TOOL_CALL_LIMIT,
        )
        self.assertGreater(
            mcp_rate_limit.MCP_AUTHENTICATED_PROTOCOL_LIMIT,
            mcp_rate_limit.MCP_ANONYMOUS_PROTOCOL_LIMIT,
        )

    async def test_fail_open_when_redis_missing_or_broken(self) -> None:
        request = _request(None, xff="1.2.3.4")
        await enforce_mcp_rate_limit(request, method="tools/call", user_id=0)

        class BrokenRedis:
            async def incr(self, key: str) -> int:
                raise ConnectionError("redis down")

        request = _request(BrokenRedis(), xff="1.2.3.4")
        await enforce_mcp_rate_limit(request, method="tools/call", user_id=0)


class RateLimitedProjectionTests(unittest.TestCase):
    def test_projection_is_http_429_with_jsonrpc_error_and_retry_after(self) -> None:
        projection = mcp_rate_limited_projection("req-1")
        self.assertEqual(projection.status_code, 429)
        self.assertEqual(
            projection.headers["Retry-After"], str(MCP_RATE_LIMIT_WINDOW_SECONDS)
        )
        self.assertIn("MCP-Protocol-Version", projection.headers)
        self.assertEqual(projection.body["id"], "req-1")
        self.assertEqual(projection.body["error"]["code"], MCP_JSONRPC_RATE_LIMITED)


class _StubRepositories:
    documents = None
    rank_snapshots = None
    project_collections = None


class McpRouteRateLimitContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = FakeRedis()
        app = FastAPI()
        app.include_router(routes_mcp.router, prefix="/api")
        app.state.redis = self.redis
        app.dependency_overrides[OptionalMcpUser] = lambda: None
        app.dependency_overrides[get_application_repositories] = (
            lambda: _StubRepositories()
        )
        app.dependency_overrides[get_briefing_repository] = lambda: None
        app.dependency_overrides[get_project_search_runtime] = lambda: SimpleNamespace(
            search_projects=None
        )
        self.app = app
        self.client = TestClient(app)
        # TestClient 直连对端（"testclient"）默认不可信；既有 XFF 用例
        # 按可信代理路径断言，这里显式信任对端，等效生产 nginx 回源。
        self._trust_patcher = patch.object(
            client_ip_module, "is_trusted_proxy", return_value=True
        )
        self._trust_patcher.start()
        self.addCleanup(self._trust_patcher.stop)

    @staticmethod
    def _tool_call(request_id: int) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": "no_such_tool", "arguments": {}},
        }

    def test_tool_call_exceeding_limit_returns_429_with_retry_after(self) -> None:
        with patch.object(mcp_rate_limit, "MCP_ANONYMOUS_TOOL_CALL_LIMIT", 2):
            for request_id in (1, 2):
                response = self.client.post(
                    "/api/mcp",
                    json=self._tool_call(request_id),
                    headers={"X-Forwarded-For": "1.2.3.4"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["result"]["isError"])
            response = self.client.post(
                "/api/mcp",
                json=self._tool_call(3),
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            self.assertEqual(response.status_code, 429)
            self.assertEqual(
                response.headers["Retry-After"], str(MCP_RATE_LIMIT_WINDOW_SECONDS)
            )
            payload = response.json()
            self.assertEqual(payload["id"], 3)
            self.assertEqual(payload["error"]["code"], MCP_JSONRPC_RATE_LIMITED)

    def test_protocol_methods_use_independent_bucket(self) -> None:
        with patch.object(mcp_rate_limit, "MCP_ANONYMOUS_TOOL_CALL_LIMIT", 1):
            self.client.post(
                "/api/mcp",
                json=self._tool_call(1),
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            throttled = self.client.post(
                "/api/mcp",
                json=self._tool_call(2),
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            self.assertEqual(throttled.status_code, 429)
            protocol = self.client.post(
                "/api/mcp",
                json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            self.assertEqual(protocol.status_code, 200)
            self.assertIn("tools", protocol.json()["result"])

    def test_distinct_ips_have_isolated_quotas(self) -> None:
        with patch.object(mcp_rate_limit, "MCP_ANONYMOUS_TOOL_CALL_LIMIT", 1):
            self.client.post(
                "/api/mcp",
                json=self._tool_call(1),
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            other = self.client.post(
                "/api/mcp",
                json=self._tool_call(2),
                headers={"X-Forwarded-For": "5.6.7.8"},
            )
            self.assertEqual(other.status_code, 200)

    def test_spoofed_xff_from_untrusted_peer_shares_quota(self) -> None:
        # 直连对端不可信时忽略 XFF：不同伪造值归并同一对端桶，无法借
        # 换头拆分配额（等效攻击者绕过 nginx 直连后端的场景）。
        self._trust_patcher.stop()
        with patch.object(mcp_rate_limit, "MCP_ANONYMOUS_TOOL_CALL_LIMIT", 1):
            first = self.client.post(
                "/api/mcp",
                json=self._tool_call(1),
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            self.assertEqual(first.status_code, 200)
            throttled = self.client.post(
                "/api/mcp",
                json=self._tool_call(2),
                headers={"X-Forwarded-For": "5.6.7.8"},
            )
            self.assertEqual(throttled.status_code, 429)

    def test_malformed_requests_are_not_charged_quota(self) -> None:
        with patch.object(mcp_rate_limit, "MCP_ANONYMOUS_PROTOCOL_LIMIT", 1):
            for _ in range(3):
                response = self.client.post(
                    "/api/mcp",
                    content=b"not-json",
                    headers={
                        "Content-Type": "application/json",
                        "X-Forwarded-For": "1.2.3.4",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("error", response.json())
            self.assertEqual(len(self.redis.values), 0)

    def test_fail_open_when_redis_unavailable(self) -> None:
        class BrokenRedis:
            async def incr(self, key: str) -> int:
                raise ConnectionError("redis down")

        self.app.state.redis = BrokenRedis()
        with patch.object(mcp_rate_limit, "MCP_ANONYMOUS_TOOL_CALL_LIMIT", 1):
            for request_id in (1, 2, 3):
                response = self.client.post(
                    "/api/mcp",
                    json=self._tool_call(request_id),
                    headers={"X-Forwarded-For": "1.2.3.4"},
                )
                self.assertEqual(response.status_code, 200)

    def test_authenticated_caller_uses_user_scoped_bucket(self) -> None:
        self.app.dependency_overrides[OptionalMcpUser] = lambda: {
            "user_id": 42,
            "scopes": frozenset(),
        }
        with patch.object(mcp_rate_limit, "MCP_AUTHENTICATED_TOOL_CALL_LIMIT", 2):
            for request_id in (1, 2):
                response = self.client.post(
                    "/api/mcp", json=self._tool_call(request_id)
                )
                self.assertEqual(response.status_code, 200)
            response = self.client.post("/api/mcp", json=self._tool_call(3))
            self.assertEqual(response.status_code, 429)
        self.assertIn("ratelimit:mcp.tool_call:user:42", self.redis.values)


if __name__ == "__main__":
    unittest.main()
