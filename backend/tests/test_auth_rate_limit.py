"""认证端点速率限制与 OTP 尝试上限契约测试。"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_auth
from backend.app.api.dependencies import get_user_account_repository
from backend.app.services.auth.rate_limit import (
    RateLimitExceededError,
    clear_login_failures,
    get_login_failure_count,
    hit_rate_limit,
    record_login_failure,
)
from backend.tests.test_email_service_contracts import FakeRedis


class HitRateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_counts_hits_within_window_and_sets_ttl_once(self) -> None:
        redis = FakeRedis()
        for expected in (1, 2, 3):
            count = await hit_rate_limit(
                redis, action="login", identity="1.2.3.4", limit=10, window_seconds=600
            )
            self.assertEqual(count, expected)
        self.assertEqual(redis.expirations["ratelimit:login:1.2.3.4"], 600)
        self.assertEqual(redis.calls.count(("expire", "ratelimit:login:1.2.3.4", 600)), 1)

    async def test_raises_when_limit_exceeded(self) -> None:
        redis = FakeRedis()
        for _ in range(2):
            await hit_rate_limit(
                redis, action="login", identity="1.2.3.4", limit=2, window_seconds=600
            )
        with self.assertRaises(RateLimitExceededError):
            await hit_rate_limit(
                redis, action="login", identity="1.2.3.4", limit=2, window_seconds=600
            )

    async def test_actions_and_identities_are_isolated(self) -> None:
        redis = FakeRedis()
        await hit_rate_limit(
            redis, action="login", identity="1.2.3.4", limit=1, window_seconds=600
        )
        # 不同 action / 不同 identity 互不影响
        count = await hit_rate_limit(
            redis, action="register", identity="1.2.3.4", limit=1, window_seconds=600
        )
        self.assertEqual(count, 1)
        count = await hit_rate_limit(
            redis, action="login", identity="5.6.7.8", limit=1, window_seconds=600
        )
        self.assertEqual(count, 1)


class LoginFailureCounterTests(unittest.IsolatedAsyncioTestCase):
    """登录失败计数（锁定语义）：读数、累计、成功清零的原子契约。"""

    async def test_missing_key_reads_zero(self) -> None:
        redis = FakeRedis()
        self.assertEqual(
            await get_login_failure_count(redis, email="user@example.com"), 0
        )

    async def test_record_accumulates_and_sets_ttl_once(self) -> None:
        redis = FakeRedis()
        for expected in (1, 2, 3):
            count = await record_login_failure(
                redis, email="user@example.com", window_seconds=3600
            )
            self.assertEqual(count, expected)
        self.assertEqual(redis.expirations["loginfail:user@example.com"], 3600)
        self.assertEqual(
            redis.calls.count(("expire", "loginfail:user@example.com", 3600)), 1
        )
        self.assertEqual(
            await get_login_failure_count(redis, email="user@example.com"), 3
        )

    async def test_clear_resets_counter(self) -> None:
        redis = FakeRedis()
        await record_login_failure(redis, email="user@example.com", window_seconds=3600)
        await clear_login_failures(redis, email="user@example.com")
        self.assertEqual(
            await get_login_failure_count(redis, email="user@example.com"), 0
        )


class _StubUserAccountRepository:
    """登录必然失败（用户不存在）的最小仓储替身。"""

    def get_user_by_email(self, email: str) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        def _noop(*args: Any, **kwargs: Any) -> None:
            return None

        return _noop


class AuthRateLimitRouteContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = FakeRedis()
        self.repository = _StubUserAccountRepository()
        app = FastAPI()
        app.include_router(routes_auth.router, prefix="/api")
        app.state.redis = self.redis
        app.dependency_overrides[get_user_account_repository] = lambda: self.repository
        self.client = TestClient(app)

    def test_login_allows_up_to_limit_then_returns_429(self) -> None:
        payload = {"email": "user@example.com", "password": "wrong-password"}
        for attempt in range(10):
            response = self.client.post("/api/auth/login", json=payload)
            self.assertEqual(response.status_code, 401, f"attempt {attempt + 1}")
        response = self.client.post("/api/auth/login", json=payload)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["detail"], "请求过于频繁，请稍后再试")

    def test_login_per_account_throttle_covers_distributed_ips(self) -> None:
        """per-账号节流：分布式 IP 对同一邮箱的爆破归并到单一账号桶。"""
        from backend.app.core import client_ip as client_ip_module

        payload = {"email": "user@example.com", "password": "wrong-password"}
        # 可信代理口径下每次请求换不同来源 IP：per-IP 桶各自只计 1 次
        with patch.object(client_ip_module, "is_trusted_proxy", return_value=True):
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

    def test_login_per_account_throttle_normalizes_domain_casing(self) -> None:
        """域名大小写变体（User@EXAMPLE.com）不拆分 per-账号桶。"""
        payload = {"email": "user@EXAMPLE.com", "password": "wrong-password"}
        for attempt in range(10):
            response = self.client.post("/api/auth/login", json=payload)
            self.assertEqual(response.status_code, 401, f"attempt {attempt + 1}")
        # per-IP 桶已达上限时先命中 IP 桶；此处账号桶与 IP 桶同限，429 即归并生效
        response = self.client.post("/api/auth/login", json=payload)
        self.assertEqual(response.status_code, 429)

    def test_login_lockout_rejects_after_failure_threshold(self) -> None:
        """失败计数达阈值的账号直接 429（含密码正确者），且不触碰密码核验。"""
        self.redis.values["loginfail:user@example.com"] = 20
        payload = {"email": "user@example.com", "password": "any-password"}
        response = self.client.post("/api/auth/login", json=payload)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            response.json()["detail"], "失败次数过多，账号已临时锁定，请稍后再试"
        )
        # 阈值之下不受影响
        self.redis.values["loginfail:user@example.com"] = 19
        response = self.client.post("/api/auth/login", json=payload)
        self.assertEqual(response.status_code, 401)

    def test_login_failure_increments_counter_and_success_clears_it(self) -> None:
        payload = {"email": "user@example.com", "password": "wrong-password"}
        response = self.client.post("/api/auth/login", json=payload)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.redis.values["loginfail:user@example.com"], 1)
        self.assertEqual(self.redis.expirations["loginfail:user@example.com"], 3600)

        # 登录成功（用户存在且密码核验通过）后失败计数清零
        self.repository.get_user_by_email = lambda email: {
            "id": 7,
            "email": "user@example.com",
            "role": "user",
            "hashed_password": "stored-hash",
        }
        with (
            patch.object(routes_auth, "verify_password", return_value=True),
            patch.object(
                routes_auth, "create_access_token", return_value="signed-token"
            ),
        ):
            response = self.client.post("/api/auth/login", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("loginfail:user@example.com", self.redis.values)

    def test_send_email_otp_is_rate_limited(self) -> None:
        payload = {"email": "user@example.com"}
        with patch.object(routes_auth, "_get_email_service") as email_service:
            email_service.return_value.send_otp = AsyncMock(return_value=None)
            for _ in range(5):
                response = self.client.post("/api/auth/send-email-otp", json=payload)
                self.assertEqual(response.status_code, 200)
            response = self.client.post("/api/auth/send-email-otp", json=payload)
            self.assertEqual(response.status_code, 429)

    def test_rate_limit_fail_open_when_redis_unavailable(self) -> None:
        class BrokenRedis:
            async def incr(self, key: str) -> int:
                raise ConnectionError("redis down")

        app = FastAPI()
        app.include_router(routes_auth.router, prefix="/api")
        app.state.redis = BrokenRedis()
        app.dependency_overrides[get_user_account_repository] = (
            _StubUserAccountRepository
        )
        client = TestClient(app)
        payload = {"email": "user@example.com", "password": "wrong-password"}
        # Redis 故障时放行（返回业务 401 而非 429/500）
        response = client.post("/api/auth/login", json=payload)
        self.assertEqual(response.status_code, 401)

    def test_no_redis_configured_skips_rate_limit(self) -> None:
        app = FastAPI()
        app.include_router(routes_auth.router, prefix="/api")
        app.state.redis = None
        app.dependency_overrides[get_user_account_repository] = (
            _StubUserAccountRepository
        )
        client = TestClient(app)
        payload = {"email": "user@example.com", "password": "wrong-password"}
        for _ in range(12):
            response = client.post("/api/auth/login", json=payload)
            self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
