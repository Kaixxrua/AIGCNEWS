"""RSS feed token 自服务管理端点契约测试。

覆盖 GET /api/auth/me/feed-token 与 POST /api/auth/me/feed-token/rotate：
  - GET 幂等：返回仓储回显的同一枚 token（created=False），首次签发 created=True；
  - 签发明文材料形态：aigc_feed_ 前缀、SHA-256 hash、AES-GCM 密封信封可往返；
  - rotate：吊销旧 + 签发新、no-store 响应头、UniqueViolation → 409、限速 429；
  - 加密密钥未配置时两端点均 503（绝不退化为明文存储）。
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_auth
from backend.app.api.dependencies import get_feed_token_repository
from backend.app.core.auth import hash_feed_token
from backend.app.domain.wechat_secret_box import WeChatSecretBox
from backend.app.services.auth.rate_limit import RateLimitExceededError


def _test_box() -> WeChatSecretBox:
    return WeChatSecretBox.generate_for_test()


class FeedTokenManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(routes_auth.router, prefix="/api")

        async def user():
            return {"user_id": 7, "email": "user@example.com", "role": "user"}

        app.dependency_overrides[routes_auth.RequireUser] = user
        self.repository = MagicMock()
        app.dependency_overrides[get_feed_token_repository] = lambda: self.repository
        self.app = app
        self.client = TestClient(app)

    def test_get_returns_existing_token_with_no_store_headers(self) -> None:
        self.repository.get_or_create_feed_token.return_value = {
            "token": "aigc_feed_stored",
            "token_hint": "aigc_feed_sto...ored",
            "created": False,
            "created_at": "2026-08-20T01:02:03Z",
        }
        with patch.object(routes_auth, "build_feed_token_secret_box", return_value=_test_box()):
            response = self.client.get("/api/auth/me/feed-token")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["token"], "aigc_feed_stored")
        self.assertEqual(response.json()["created"], False)
        self.assertEqual(response.json()["created_at"], "2026-08-20T01:02:03Z")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")
        self.assertEqual(
            self.repository.get_or_create_feed_token.call_args.kwargs["user_id"], 7
        )

    def test_get_first_call_seals_material_and_returns_plaintext(self) -> None:
        box = _test_box()

        def capture(*, user_id, token_hash, token_hint, token_encrypted):
            envelope = json.loads(token_encrypted)
            token = box.unseal(envelope)
            # 落库材料契约：hash 是明文的 SHA-256，hint 是明文的掩码，
            # 信封可解密回明文且不等于明文（绝不明文落库）
            self.assertTrue(token.startswith("aigc_feed_"))
            self.assertEqual(token_hash, hash_feed_token(token))
            self.assertNotIn(token, token_encrypted)
            self.assertEqual(token_hint, f"{token[:14]}...{token[-4:]}")
            return {
                "token": token,
                "token_hint": token_hint,
                "created": True,
                "created_at": "2026-08-25T08:00:00Z",
            }

        self.repository.get_or_create_feed_token.side_effect = capture
        with patch.object(routes_auth, "build_feed_token_secret_box", return_value=box):
            response = self.client.get("/api/auth/me/feed-token")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["token"].startswith("aigc_feed_"))
        self.assertEqual(response.json()["created"], True)

    def test_get_without_encryption_key_returns_503(self) -> None:
        with patch.object(routes_auth, "build_feed_token_secret_box", return_value=None):
            response = self.client.get("/api/auth/me/feed-token")
        self.assertEqual(response.status_code, 503)
        self.assertIn("加密密钥", response.json()["detail"])
        self.repository.get_or_create_feed_token.assert_not_called()

    def test_rotate_returns_new_token_with_no_store_headers(self) -> None:
        self.repository.rotate_feed_token.return_value = {
            "token": "aigc_feed_new",
            "token_hint": "aigc_feed_new...new!",
            "created": True,
            "created_at": "2026-08-25T09:00:00Z",
            "revoked_count": 1,
        }
        with patch.object(routes_auth, "build_feed_token_secret_box", return_value=_test_box()):
            response = self.client.post("/api/auth/me/feed-token/rotate")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["token"], "aigc_feed_new")
        self.assertEqual(response.json()["created"], True)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")
        self.assertEqual(self.repository.rotate_feed_token.call_args.kwargs["user_id"], 7)

    def test_rotate_unique_violation_returns_409(self) -> None:
        from psycopg import errors as pg_errors

        self.repository.rotate_feed_token.side_effect = pg_errors.UniqueViolation("dup")
        with patch.object(routes_auth, "build_feed_token_secret_box", return_value=_test_box()):
            response = self.client.post("/api/auth/me/feed-token/rotate")
        self.assertEqual(response.status_code, 409)

    def test_rotate_rate_limited_returns_429(self) -> None:
        self.app.state.redis = MagicMock()
        with patch.object(
            routes_auth, "hit_rate_limit", side_effect=RateLimitExceededError("limited")
        ):
            response = self.client.post("/api/auth/me/feed-token/rotate")
        self.assertEqual(response.status_code, 429)
        self.repository.rotate_feed_token.assert_not_called()

    def test_rotate_without_encryption_key_returns_503(self) -> None:
        with patch.object(routes_auth, "build_feed_token_secret_box", return_value=None):
            response = self.client.post("/api/auth/me/feed-token/rotate")
        self.assertEqual(response.status_code, 503)
        self.repository.rotate_feed_token.assert_not_called()


if __name__ == "__main__":
    unittest.main()
