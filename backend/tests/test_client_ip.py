"""可信代理感知的客户端 IP 解析契约测试。

覆盖：helper 单元行为（可信/不可信对端、CIDR、非法配置）、
认证限速路由的 XFF 伪造隔离、访客统计中间件的对端采信口径。
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.app.api import routes_auth
from backend.app.api.dependencies import get_user_account_repository
from backend.app.core import client_ip as client_ip_module
from backend.app.core.client_ip import (
    _reset_trusted_proxy_cache,
    client_ip_from_request,
    is_trusted_proxy,
)
from backend.app.main import VisitorTrackingMiddleware
from backend.tests.test_email_service_contracts import FakeRedis


def _request(
    *,
    client: tuple[str, int] | None = ("9.9.9.9", 5000),
    xff: str | None = None,
) -> Request:
    headers = []
    if xff:
        headers.append((b"x-forwarded-for", xff.encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/x",
            "headers": headers,
            "client": client,
            "app": SimpleNamespace(state=SimpleNamespace(redis=None)),
        }
    )


class TrustedProxyParsingTests(unittest.TestCase):
    def tearDown(self) -> None:
        _reset_trusted_proxy_cache()

    def test_default_trusts_loopback_only(self) -> None:
        self.assertTrue(is_trusted_proxy("127.0.0.1"))
        self.assertTrue(is_trusted_proxy("::1"))
        self.assertFalse(is_trusted_proxy("9.9.9.9"))
        self.assertFalse(is_trusted_proxy("192.168.1.10"))

    def test_cidr_entries_trust_compose_network_peers(self) -> None:
        with patch.object(
            client_ip_module.settings,
            "trusted_proxy_ips",
            "127.0.0.1,::1,172.16.0.0/12",
        ):
            _reset_trusted_proxy_cache()
            self.assertTrue(is_trusted_proxy("172.19.0.3"))
            self.assertFalse(is_trusted_proxy("9.9.9.9"))

    def test_invalid_entries_are_ignored(self) -> None:
        with patch.object(
            client_ip_module.settings,
            "trusted_proxy_ips",
            "not-an-ip,127.0.0.1,,",
        ):
            _reset_trusted_proxy_cache()
            self.assertTrue(is_trusted_proxy("127.0.0.1"))
            self.assertFalse(is_trusted_proxy("9.9.9.9"))

    def test_unparseable_peer_is_never_trusted(self) -> None:
        # starlette TestClient 的对端名为 "testclient"，不是 IP 字面量
        self.assertFalse(is_trusted_proxy("testclient"))
        self.assertFalse(is_trusted_proxy(""))


class ClientIpFromRequestTests(unittest.TestCase):
    def tearDown(self) -> None:
        _reset_trusted_proxy_cache()

    def test_trusted_peer_honors_first_forwarded_for_hop(self) -> None:
        request = _request(client=("127.0.0.1", 5000), xff="1.2.3.4, 10.0.0.1")
        self.assertEqual(client_ip_from_request(request), "1.2.3.4")

    def test_untrusted_peer_ignores_forwarded_for(self) -> None:
        request = _request(client=("9.9.9.9", 5000), xff="1.2.3.4")
        self.assertEqual(client_ip_from_request(request), "9.9.9.9")

    def test_trusted_peer_without_forwarded_for_uses_peer(self) -> None:
        request = _request(client=("127.0.0.1", 5000))
        self.assertEqual(client_ip_from_request(request), "127.0.0.1")

    def test_trusted_peer_with_blank_forwarded_for_uses_peer(self) -> None:
        request = _request(client=("127.0.0.1", 5000), xff="  ")
        self.assertEqual(client_ip_from_request(request), "127.0.0.1")

    def test_missing_client_falls_back_to_unknown(self) -> None:
        request = _request(client=None, xff="1.2.3.4")
        self.assertEqual(client_ip_from_request(request), "unknown")


class _StubUserAccountRepository:
    """登录必然失败（用户不存在）的最小仓储替身。"""

    def get_user_by_email(self, email: str) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        def _noop(*args: Any, **kwargs: Any) -> None:
            return None

        return _noop


class AuthRateLimitXffSpoofContracts(unittest.TestCase):
    """伪造 XFF 不得拆分限速桶：不可信对端一律按直连对端归因。"""

    def setUp(self) -> None:
        self.redis = FakeRedis()
        app = FastAPI()
        app.include_router(routes_auth.router, prefix="/api")
        app.state.redis = self.redis
        app.dependency_overrides[get_user_account_repository] = (
            _StubUserAccountRepository
        )
        self.client = TestClient(app)

    def test_spoofed_xff_does_not_bypass_login_rate_limit(self) -> None:
        payload = {"email": "user@example.com", "password": "wrong-password"}
        # 每请求换一个伪造 XFF：旧实现按 XFF 分桶永不触发限速，
        # 修复后不可信对端忽略 XFF，全部计入同一直连对端桶。
        for attempt in range(10):
            response = self.client.post(
                "/api/auth/login",
                json=payload,
                headers={"X-Forwarded-For": f"203.0.113.{attempt + 1}"},
            )
            self.assertEqual(response.status_code, 401, f"attempt {attempt + 1}")
        response = self.client.post(
            "/api/auth/login",
            json=payload,
            headers={"X-Forwarded-For": "203.0.113.250"},
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["detail"], "请求过于频繁，请稍后再试")
        # 所有尝试都归并到同一直连对端桶（TestClient 对端为 "testclient"）；
        # 另一桶为 per-账号（email）节流桶。伪造的 XFF 不产生任何桶。
        self.assertEqual(
            set(self.redis.values),
            {
                "ratelimit:auth.login:testclient",
                "ratelimit:auth.login.account:user@example.com",
            },
        )


class _SetRecordingRedis:
    """访客中间件需要的最小 Redis：SADD/EXPIRE 记录。"""

    def __init__(self) -> None:
        self.sets: dict[str, set[str]] = {}
        self.expirations: dict[str, int] = {}

    async def sadd(self, key: str, member: str) -> int:
        bucket = self.sets.setdefault(key, set())
        before = len(bucket)
        bucket.add(member)
        return len(bucket) - before

    async def expire(self, key: str, seconds: int) -> None:
        self.expirations[key] = seconds


class VisitorTrackingMiddlewareContracts(unittest.TestCase):
    def _build_client(self) -> tuple[TestClient, _SetRecordingRedis]:
        redis = _SetRecordingRedis()
        app = FastAPI()

        @app.get("/ping")
        def _ping() -> dict[str, bool]:
            return {"ok": True}

        app.add_middleware(VisitorTrackingMiddleware)
        app.state.redis = redis
        return TestClient(app), redis

    def test_untrusted_peer_xff_does_not_pollute_visitor_set(self) -> None:
        client, redis = self._build_client()
        response = client.get("/ping", headers={"X-Forwarded-For": "1.2.3.4"})
        self.assertEqual(response.status_code, 200)
        recorded = next(iter(redis.sets.values()))
        # 直连对端（"testclient"）不可信：访客集合记录对端而非伪造的 XFF
        self.assertEqual(recorded, {"testclient"})

    def test_trusted_peer_xff_is_recorded(self) -> None:
        client, redis = self._build_client()
        with patch.object(client_ip_module, "is_trusted_proxy", return_value=True):
            response = client.get(
                "/ping", headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.1"}
            )
        self.assertEqual(response.status_code, 200)
        recorded = next(iter(redis.sets.values()))
        self.assertEqual(recorded, {"1.2.3.4"})


if __name__ == "__main__":
    unittest.main()
