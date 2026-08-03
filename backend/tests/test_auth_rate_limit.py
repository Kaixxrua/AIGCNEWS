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
    hit_rate_limit,
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
        app = FastAPI()
        app.include_router(routes_auth.router, prefix="/api")
        app.state.redis = self.redis
        app.dependency_overrides[get_user_account_repository] = (
            _StubUserAccountRepository
        )
        self.client = TestClient(app)

    def test_login_allows_up_to_limit_then_returns_429(self) -> None:
        payload = {"email": "user@example.com", "password": "wrong-password"}
        for attempt in range(10):
            response = self.client.post("/api/auth/login", json=payload)
            self.assertEqual(response.status_code, 401, f"attempt {attempt + 1}")
        response = self.client.post("/api/auth/login", json=payload)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["detail"], "请求过于频繁，请稍后再试")

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
