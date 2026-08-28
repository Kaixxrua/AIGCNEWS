"""DSH 专用 MCP token ensure/rotate 端点契约测试。

覆盖 POST /api/auth/me/mcp-tokens/dsh/ensure 与 .../dsh/rotate：
  - ensure 幂等：首次签发 created（reused=False），之后解密回显同一枚
    （reused=True）；跨刷新复用依赖服务端密封材料，浏览器不落盘；
  - 签发材料形态：aigc_mcp_ 前缀、SHA-256 hash、AES-GCM 密封信封可往返、
    明文不出现在落库材料中；purpose/scope/客户端标识全部由服务端固定，
    请求体携带的 membership_tier/group/scopes 一律被忽略；
  - legacy hash-only DSH 行：409 + detail.code=dsh_token_recovery_required，
    绝不静默吊销仍在使用的旧 token；
  - rotate：吊销旧 + 签发新、revoked_count 透传、限速 429、
    UniqueViolation → 409；
  - 两端点均 no-store/no-cache；加密密钥未配置时 503 且仓储不被调用
    （绝不退化为明文存储）。
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_auth
from backend.app.api.dependencies import get_mcp_access_token_repository
from backend.app.core.auth import hash_mcp_token
from backend.app.domain.wechat_secret_box import WeChatSecretBox
from backend.app.services.auth.rate_limit import RateLimitExceededError


def _test_box() -> WeChatSecretBox:
    return WeChatSecretBox.generate_for_test()


def _metadata() -> dict:
    return {
        "id": 21,
        "user_id": 7,
        "token_hint": "aigc_mcp_ab...wxyz",
        "scopes": ["projects:favorites:read"],
        "client_type": "other",
        "client_label": "dsh-aigc-radar",
        "purpose": "dsh",
        "expires_at": None,
        "revoked_at": None,
        "deleted_at": None,
        "created_at": "2026-08-28T01:02:03Z",
        "last_used_at": None,
    }


class DshMcpTokenManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(routes_auth.router, prefix="/api")

        async def user():
            return {"user_id": 7, "email": "user@example.com", "role": "user"}

        app.dependency_overrides[routes_auth.RequireUser] = user
        self.repository = MagicMock()
        app.dependency_overrides[get_mcp_access_token_repository] = lambda: self.repository
        self.app = app
        self.client = TestClient(app)

    def test_ensure_first_call_seals_material_and_returns_plaintext(self) -> None:
        box = _test_box()

        def capture(
            *, user_id, token_hash, token_hint, token_encrypted, scopes, client_type, client_label
        ):
            envelope = json.loads(token_encrypted)
            token = box.unseal(envelope)
            # 落库材料契约：hash 是明文的 SHA-256，hint 是明文掩码，信封可
            # 解密回明文且不等于明文（绝不明文落库）
            self.assertTrue(token.startswith("aigc_mcp_"))
            self.assertEqual(token_hash, hash_mcp_token(token))
            self.assertNotIn(token, token_encrypted)
            self.assertEqual(token_hint, f"{token[:12]}...{token[-4:]}")
            self.assertEqual(scopes, ["projects:favorites:read"])
            self.assertEqual(client_type, "other")
            self.assertEqual(client_label, "dsh-aigc-radar")
            return {"status": "created", "token": token, "token_metadata": _metadata()}

        self.repository.ensure_user_dsh_mcp_token.side_effect = capture
        with patch.object(routes_auth, "build_dsh_mcp_token_secret_box", return_value=box):
            response = self.client.post("/api/auth/me/mcp-tokens/dsh/ensure")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["token"].startswith("aigc_mcp_"))
        self.assertEqual(body["reused"], False)
        self.assertEqual(body["token_metadata"]["purpose"], "dsh")
        self.assertNotIn("revoked_count", body)
        self.assertEqual(
            self.repository.ensure_user_dsh_mcp_token.call_args.kwargs["user_id"], 7
        )

    def test_ensure_reused_returns_same_token_with_no_store_headers(self) -> None:
        self.repository.ensure_user_dsh_mcp_token.return_value = {
            "status": "reused",
            "token": "aigc_mcp_stored",
            "token_metadata": _metadata(),
        }
        with patch.object(
            routes_auth, "build_dsh_mcp_token_secret_box", return_value=_test_box()
        ):
            response = self.client.post("/api/auth/me/mcp-tokens/dsh/ensure")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["token"], "aigc_mcp_stored")
        self.assertEqual(response.json()["reused"], True)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")

    def test_ensure_ignores_client_supplied_membership_and_scope_fields(self) -> None:
        """会员档位永远以 token 属主在 users 表中的实时值为准：请求体携带的
        membership_tier/group/scopes/client_* 不得影响服务端固定参数。"""
        self.repository.ensure_user_dsh_mcp_token.return_value = {
            "status": "reused",
            "token": "aigc_mcp_stored",
            "token_metadata": _metadata(),
        }
        with patch.object(
            routes_auth, "build_dsh_mcp_token_secret_box", return_value=_test_box()
        ):
            response = self.client.post(
                "/api/auth/me/mcp-tokens/dsh/ensure",
                json={
                    "membership_tier": "member",
                    "group": "vip",
                    "scopes": ["admin:all"],
                    "client_type": "cli",
                    "purpose": "generic",
                },
            )

        self.assertEqual(response.status_code, 200)
        kwargs = self.repository.ensure_user_dsh_mcp_token.call_args.kwargs
        self.assertEqual(kwargs["scopes"], ["projects:favorites:read"])
        self.assertEqual(kwargs["client_type"], "other")
        self.assertEqual(kwargs["client_label"], "dsh-aigc-radar")
        self.assertNotIn("membership_tier", kwargs)
        self.assertNotIn("group", kwargs)
        self.assertNotIn("purpose", kwargs)

    def test_ensure_legacy_hash_only_token_returns_409_recovery_code(self) -> None:
        self.repository.ensure_user_dsh_mcp_token.return_value = {
            "status": "recovery_required",
            "legacy_count": 1,
        }
        with patch.object(
            routes_auth, "build_dsh_mcp_token_secret_box", return_value=_test_box()
        ):
            response = self.client.post("/api/auth/me/mcp-tokens/dsh/ensure")

        self.assertEqual(response.status_code, 409)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "dsh_token_recovery_required")
        self.assertIn("重新生成", detail["message"])

    def test_ensure_without_encryption_key_returns_503(self) -> None:
        with patch.object(routes_auth, "build_dsh_mcp_token_secret_box", return_value=None):
            response = self.client.post("/api/auth/me/mcp-tokens/dsh/ensure")

        self.assertEqual(response.status_code, 503)
        self.assertIn("加密密钥", response.json()["detail"])
        self.repository.ensure_user_dsh_mcp_token.assert_not_called()

    def test_ensure_unique_violation_returns_409_retry_message(self) -> None:
        from psycopg import errors as pg_errors

        self.repository.ensure_user_dsh_mcp_token.side_effect = pg_errors.UniqueViolation(
            "dup"
        )
        with patch.object(
            routes_auth, "build_dsh_mcp_token_secret_box", return_value=_test_box()
        ):
            response = self.client.post("/api/auth/me/mcp-tokens/dsh/ensure")

        self.assertEqual(response.status_code, 409)
        # 并发冲突 409 是可重试的字符串 detail，与 recovery 的结构化 detail 区分
        self.assertEqual(response.json()["detail"], "DSH token 生成冲突，请重试")

    def test_rotate_returns_new_token_and_revoked_count(self) -> None:
        self.repository.rotate_user_dsh_mcp_token.return_value = {
            "status": "rotated",
            "token": "aigc_mcp_new",
            "token_metadata": _metadata(),
            "revoked_count": 2,
        }
        with patch.object(
            routes_auth, "build_dsh_mcp_token_secret_box", return_value=_test_box()
        ):
            response = self.client.post("/api/auth/me/mcp-tokens/dsh/rotate")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["token"], "aigc_mcp_new")
        self.assertEqual(body["reused"], False)
        self.assertEqual(body["revoked_count"], 2)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")
        kwargs = self.repository.rotate_user_dsh_mcp_token.call_args.kwargs
        self.assertEqual(kwargs["user_id"], 7)
        self.assertEqual(kwargs["scopes"], ["projects:favorites:read"])
        self.assertEqual(kwargs["client_label"], "dsh-aigc-radar")

    def test_rotate_rate_limited_returns_429(self) -> None:
        self.app.state.redis = MagicMock()
        with patch.object(
            routes_auth, "hit_rate_limit", side_effect=RateLimitExceededError("limited")
        ):
            response = self.client.post("/api/auth/me/mcp-tokens/dsh/rotate")

        self.assertEqual(response.status_code, 429)
        self.repository.rotate_user_dsh_mcp_token.assert_not_called()

    def test_rotate_without_encryption_key_returns_503(self) -> None:
        with patch.object(routes_auth, "build_dsh_mcp_token_secret_box", return_value=None):
            response = self.client.post("/api/auth/me/mcp-tokens/dsh/rotate")

        self.assertEqual(response.status_code, 503)
        self.repository.rotate_user_dsh_mcp_token.assert_not_called()

    def test_rotate_unique_violation_returns_409(self) -> None:
        from psycopg import errors as pg_errors

        self.repository.rotate_user_dsh_mcp_token.side_effect = pg_errors.UniqueViolation(
            "dup"
        )
        with patch.object(
            routes_auth, "build_dsh_mcp_token_secret_box", return_value=_test_box()
        ):
            response = self.client.post("/api/auth/me/mcp-tokens/dsh/rotate")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "DSH token 生成冲突，请重试")


if __name__ == "__main__":
    unittest.main()
