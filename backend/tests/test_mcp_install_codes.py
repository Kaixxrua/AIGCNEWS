"""MCP 一次性安装码：存储语义与签发/兑换端点契约（Red：认证凭证签发）。

- 存储：只存 SHA-256 摘要做键、10 分钟过期、GETDEL（或 Lua）一次性消费；格式不对的码不碰 Redis；
  Redis 不可用时 fail closed。
- 签发 POST /api/auth/me/mcp-install-codes：要登录，按用户限速，载荷绑定 JWT 的口令版本，no-store。
- 兑换 POST /api/auth/mcp-install-codes/redeem：匿名，按 IP 限速；先消费再校验，码一经提交即作废；
  账号删除、禁用或改过密码按无效码处理；mcp 用途新签一枚 Token，dsh 用途回显账号唯一的 DSH Token；
  Accept: text/plain 时只回 Token 原文；日志里不出现安装码与 Token。
"""

from __future__ import annotations

import hashlib
import json
import logging
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_auth
from backend.app.api.dependencies import get_mcp_access_token_repository, get_user_account_repository
from backend.app.core.auth import hash_mcp_token
from backend.app.domain.wechat_secret_box import WeChatSecretBox
from backend.app.services.auth.mcp_install_codes import (
    INSTALL_CODE_KEY_PREFIX,
    INSTALL_CODE_PREFIX,
    INSTALL_CODE_TTL_SECONDS,
    InstallCodePayload,
    InstallCodeStore,
    McpInstallCodeUnavailableError,
    install_code_key,
)
from backend.app.services.auth.rate_limit import RateLimitExceededError

ISSUE = "/api/auth/me/mcp-install-codes"
REDEEM = "/api/auth/mcp-install-codes/redeem"


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}
        self.calls = 0

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.calls += 1
        self.values[key] = value
        self.ttls[key] = ex

    async def getdel(self, key: str):
        self.calls += 1
        return self.values.pop(key, None)

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def ttl(self, key: str) -> int:
        return 600

    async def expire(self, key: str, seconds: int) -> bool:
        return True


class LuaOnlyRedis(FakeRedis):
    getdel = None  # 老 Redis 没有 GETDEL：走 Lua 原子取删

    async def eval(self, script: str, numkeys: int, key: str):
        assert "redis.call('DEL', KEYS[1])" in script and numkeys == 1
        return self.values.pop(key, None)


class BrokenRedis:
    async def set(self, *args, **kwargs):
        raise ConnectionError("redis down")

    async def getdel(self, key: str):
        raise ConnectionError("redis down")


class InstallCodeStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_code_is_single_use_and_stored_under_digest_with_ttl(self) -> None:
        redis = FakeRedis()
        store = InstallCodeStore(redis)
        code = await store.issue(InstallCodePayload(user_id=7, purpose="mcp", pwd_ver=3))

        self.assertTrue(code.startswith(INSTALL_CODE_PREFIX))
        self.assertGreaterEqual(len(code), len(INSTALL_CODE_PREFIX) + 43)
        (key,) = redis.values
        self.assertEqual(key, INSTALL_CODE_KEY_PREFIX + hashlib.sha256(code.encode()).hexdigest())
        self.assertEqual(key, install_code_key(code))
        self.assertNotIn(code, key)
        self.assertNotIn(code, redis.values[key])
        self.assertEqual(redis.ttls[key], INSTALL_CODE_TTL_SECONDS)
        self.assertEqual(INSTALL_CODE_TTL_SECONDS, 600)

        payload = await store.consume(code)
        self.assertEqual(payload, InstallCodePayload(user_id=7, purpose="mcp", pwd_ver=3))
        self.assertIsNone(await store.consume(code))
        self.assertEqual(redis.values, {})

    async def test_lua_fallback_is_also_single_use(self) -> None:
        store = InstallCodeStore(LuaOnlyRedis())
        code = await store.issue(InstallCodePayload(user_id=7, purpose="dsh"))
        self.assertEqual((await store.consume(code)).purpose, "dsh")
        self.assertIsNone(await store.consume(code))

    async def test_malformed_codes_never_touch_redis(self) -> None:
        redis = FakeRedis()
        store = InstallCodeStore(redis)
        for code in (None, "", 42, "aigc_mcp_" + "x" * 43, INSTALL_CODE_PREFIX + "x" * 200):
            with self.subTest(code=code):
                self.assertIsNone(await store.consume(code))
        self.assertEqual(redis.calls, 0)

    async def test_corrupt_or_foreign_payload_is_rejected_and_consumed(self) -> None:
        redis = FakeRedis()
        store = InstallCodeStore(redis)
        bad_values = (
            "not json",
            json.dumps({"user_id": 7, "purpose": "admin"}),
            json.dumps({"user_id": 7, "purpose": "mcp", "role": "admin"}),
            b"\xff\xfe",
        )
        for index, value in enumerate(bad_values):
            code = f"{INSTALL_CODE_PREFIX}corrupt{index}"
            redis.values[install_code_key(code)] = value
            with self.subTest(value=value):
                self.assertIsNone(await store.consume(code))
        self.assertEqual(redis.values, {})

    async def test_unavailable_redis_fails_closed(self) -> None:
        payload = InstallCodePayload(user_id=7, purpose="mcp")
        for redis in (None, BrokenRedis()):
            store = InstallCodeStore(redis)
            with self.subTest(redis=redis), self.assertRaises(McpInstallCodeUnavailableError):
                await store.issue(payload)
            with self.subTest(redis=redis), self.assertRaises(McpInstallCodeUnavailableError):
                await store.consume(INSTALL_CODE_PREFIX + "x" * 43)


class FakeUsers:
    def __init__(self) -> None:
        self.records: dict[int, dict[str, Any]] = {7: {"id": 7, "disabled": False, "pwd_ver": 3}}

    def get_user_by_id(self, user_id: int):
        record = self.records.get(user_id)
        return dict(record) if record is not None else None


def _secret_box() -> WeChatSecretBox:
    return WeChatSecretBox.generate_for_test()


def _metadata(label: str = "Cherry Studio") -> dict[str, Any]:
    return {"id": 31, "user_id": 7, "token_hint": "aigc_mcp_ab...wxyz", "client_label": label}


class InstallCodeRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = FakeRedis()
        self.users = FakeUsers()
        self.tokens = MagicMock()
        self.tokens.create_user_mcp_token.return_value = {"token_metadata": _metadata(), "replaced_count": 0}
        app = FastAPI()
        app.state.redis = self.redis
        app.include_router(routes_auth.router, prefix="/api")
        app.dependency_overrides[get_mcp_access_token_repository] = lambda: self.tokens
        app.dependency_overrides[get_user_account_repository] = lambda: self.users
        self.app = app
        self.client = TestClient(app, base_url="https://aigcnews.cn")
        self.sign_in()

    def sign_in(self, **claims: Any) -> None:
        identity = {"user_id": 7, "role": "user", "pwd_ver": 3, **claims}

        async def user():
            return identity

        self.app.dependency_overrides[routes_auth.RequireUser] = user

    def issue(self, purpose: str = "mcp") -> str:
        response = self.client.post(ISSUE, json={"purpose": purpose})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["code"]

    # ------------------------------------------------------------ issue

    def test_issue_returns_short_lived_code_bound_to_user_and_password_version(self) -> None:
        response = self.client.post(ISSUE, json={"purpose": "mcp"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"code", "purpose", "expires_in"})
        self.assertTrue(body["code"].startswith(INSTALL_CODE_PREFIX))
        self.assertEqual((body["purpose"], body["expires_in"]), ("mcp", 600))
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")
        stored = json.loads(self.redis.values[install_code_key(body["code"])])
        self.assertEqual(stored, {"user_id": 7, "purpose": "mcp", "pwd_ver": 3})
        self.assertEqual(self.redis.counters, {"ratelimit:auth.mcp_install_code_issue:user:7": 1})

    def test_issue_defaults_to_mcp_and_accepts_dsh(self) -> None:
        self.assertEqual(self.client.post(ISSUE, json={}).json()["purpose"], "mcp")
        self.assertEqual(self.client.post(ISSUE, json={"purpose": "dsh"}).json()["purpose"], "dsh")

    def test_issue_rejects_unknown_purpose_and_extra_fields(self) -> None:
        for body in ({"purpose": "admin"}, {"purpose": "mcp", "user_id": 1}):
            with self.subTest(body=body):
                self.assertEqual(self.client.post(ISSUE, json=body).status_code, 422)
        self.assertEqual(self.redis.values, {})

    def test_issue_requires_sign_in(self) -> None:
        del self.app.dependency_overrides[routes_auth.RequireUser]
        response = self.client.post(ISSUE, json={"purpose": "mcp"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.redis.values, {})

    def test_issue_is_rate_limited_per_user(self) -> None:
        with patch.object(routes_auth, "hit_rate_limit", side_effect=RateLimitExceededError("limited")) as hit:
            response = self.client.post(ISSUE, json={"purpose": "mcp"})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(hit.call_args.kwargs["identity"], "user:7")
        self.assertEqual(hit.call_args.kwargs["limit"], 60)
        self.assertEqual(self.redis.values, {})

    def test_issue_fails_closed_without_redis(self) -> None:
        self.app.state.redis = None
        response = self.client.post(ISSUE, json={"purpose": "mcp"})
        self.assertEqual(response.status_code, 503)

    # ------------------------------------------------------------ redeem: mcp

    def test_redeem_creates_a_token_for_the_named_client(self) -> None:
        code = self.issue()
        response = self.client.post(REDEEM, json={"code": code, "client_name": " Claude‮ Desktop "})

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body), {"purpose", "token", "token_type", "scopes"})
        self.assertEqual((body["purpose"], body["token_type"]), ("mcp", "Bearer"))
        self.assertEqual(body["scopes"], ["projects:favorites:read", "tracking:read"])
        self.assertTrue(body["token"].startswith("aigc_mcp_"))
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")
        kwargs = self.tokens.create_user_mcp_token.call_args.kwargs
        token = body["token"]
        self.assertEqual(
            kwargs,
            {
                "user_id": 7,
                "token_hash": hash_mcp_token(token),
                "token_hint": f"{token[:12]}...{token[-4:]}",
                "scopes": ["projects:favorites:read", "tracking:read"],
                "client_type": "claude",
                "client_label": "Claude Desktop",
                "expires_at": None,
            },
        )

    def test_redeem_without_client_name_uses_default_label(self) -> None:
        response = self.client.post(REDEEM, json={"code": self.issue()})
        self.assertEqual(response.status_code, 200)
        kwargs = self.tokens.create_user_mcp_token.call_args.kwargs
        self.assertEqual((kwargs["client_type"], kwargs["client_label"]), ("other", "MCP install code"))

    def test_redeem_plain_text_returns_only_the_token(self) -> None:
        response = self.client.post(
            REDEEM, json={"code": self.issue(), "client_name": "Cursor"}, headers={"Accept": "text/plain"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/plain"))
        self.assertRegex(response.text, r"^aigc_mcp_[A-Za-z0-9_-]{43}$")
        created = self.tokens.create_user_mcp_token.call_args.kwargs
        self.assertEqual(hash_mcp_token(response.text), created["token_hash"])
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_mixed_accept_header_keeps_json(self) -> None:
        response = self.client.post(
            REDEEM, json={"code": self.issue()}, headers={"Accept": "text/plain, application/json"}
        )
        self.assertEqual(response.json()["token_type"], "Bearer")

    def test_code_is_single_use(self) -> None:
        code = self.issue()
        self.assertEqual(self.client.post(REDEEM, json={"code": code}).status_code, 200)
        again = self.client.post(REDEEM, json={"code": code})
        self.assertEqual(again.status_code, 400)
        self.assertEqual(again.json()["detail"]["code"], "install_code_invalid")
        self.assertEqual(self.tokens.create_user_mcp_token.call_count, 1)

    def test_unknown_or_malformed_code_is_invalid(self) -> None:
        for code in (INSTALL_CODE_PREFIX + "x" * 43, "aigc_mcp_" + "x" * 43, ""):
            with self.subTest(code=code):
                response = self.client.post(REDEEM, json={"code": code})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["detail"]["code"], "install_code_invalid")
        self.assertEqual(self.client.post(REDEEM, json={"code": "x" * 129}).status_code, 422)
        self.tokens.create_user_mcp_token.assert_not_called()

    def test_account_changes_after_issue_void_the_code(self) -> None:
        cases = {
            "deleted": lambda: self.users.records.pop(7),
            "disabled": lambda: self.users.records[7].update(disabled=True),
            "password-changed": lambda: self.users.records[7].update(pwd_ver=4),
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                self.users = FakeUsers()
                self.app.dependency_overrides[get_user_account_repository] = lambda: self.users
                code = self.issue()
                change()
                response = self.client.post(REDEEM, json={"code": code})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["detail"]["code"], "install_code_invalid")
                self.assertNotIn(install_code_key(code), self.redis.values)
        self.tokens.create_user_mcp_token.assert_not_called()

    def test_accounts_without_password_version_column_still_redeem(self) -> None:
        self.users.records[7].pop("pwd_ver")
        self.sign_in(pwd_ver=None)
        self.assertEqual(self.client.post(REDEEM, json={"code": self.issue()}).status_code, 200)

    def test_user_removed_during_token_creation_is_invalid(self) -> None:
        self.tokens.create_user_mcp_token.side_effect = ValueError("user missing")
        response = self.client.post(REDEEM, json={"code": self.issue()})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "install_code_invalid")

    def test_redeem_is_rate_limited_per_ip_before_consuming(self) -> None:
        code = self.issue()
        with patch.object(routes_auth, "hit_rate_limit", side_effect=RateLimitExceededError("limited")) as hit:
            response = self.client.post(REDEEM, json={"code": code})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(hit.call_args.kwargs["action"], "auth.mcp_install_code_redeem")
        self.assertEqual(hit.call_args.kwargs["limit"], 20)
        self.assertIn(install_code_key(code), self.redis.values)

    def test_redeem_fails_closed_without_redis(self) -> None:
        code = self.issue()
        self.app.state.redis = None
        self.assertEqual(self.client.post(REDEEM, json={"code": code}).status_code, 503)

    def test_logs_never_contain_code_or_token(self) -> None:
        code = self.issue()
        with self.assertLogs(routes_auth.logger, level=logging.DEBUG) as captured:
            response = self.client.post(REDEEM, json={"code": code}, headers={"Accept": "text/plain"})
        output = "\n".join(captured.output)
        self.assertIn("install code redeemed user_id=7 purpose=mcp", output)
        self.assertNotIn(code, output)
        self.assertNotIn(response.text, output)

    # ------------------------------------------------------------ redeem: dsh

    def test_dsh_code_returns_the_accounts_dsh_token(self) -> None:
        self.tokens.ensure_user_dsh_mcp_token.return_value = {
            "status": "reused",
            "token": "aigc_mcp_dsh_stored",
            "token_metadata": _metadata("dsh-aigc-radar"),
        }
        code = self.issue("dsh")
        with patch.object(routes_auth, "build_dsh_mcp_token_secret_box", return_value=_secret_box()):
            response = self.client.post(
                REDEEM, json={"code": code, "client_name": "ignored"}, headers={"Accept": "text/plain"}
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.text, "aigc_mcp_dsh_stored")
        kwargs = self.tokens.ensure_user_dsh_mcp_token.call_args.kwargs
        self.assertEqual(kwargs["user_id"], 7)
        self.assertEqual((kwargs["client_type"], kwargs["client_label"]), ("other", "dsh-aigc-radar"))
        self.tokens.create_user_mcp_token.assert_not_called()

    def test_dsh_recovery_required_surfaces_and_consumes_the_code(self) -> None:
        self.tokens.ensure_user_dsh_mcp_token.return_value = {"status": "recovery_required"}
        code = self.issue("dsh")
        with patch.object(routes_auth, "build_dsh_mcp_token_secret_box", return_value=_secret_box()):
            response = self.client.post(REDEEM, json={"code": code})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "dsh_token_recovery_required")
        self.assertNotIn(install_code_key(code), self.redis.values)

    def test_dsh_without_secret_key_is_unavailable(self) -> None:
        code = self.issue("dsh")
        with patch.object(routes_auth, "build_dsh_mcp_token_secret_box", return_value=None):
            response = self.client.post(REDEEM, json={"code": code})
        self.assertEqual(response.status_code, 503)
        self.tokens.ensure_user_dsh_mcp_token.assert_not_called()


if __name__ == "__main__":
    unittest.main()
