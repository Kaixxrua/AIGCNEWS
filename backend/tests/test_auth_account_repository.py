from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_auth
from backend.app.api.dependencies import get_user_account_repository
from backend.app.core.auth import hash_password


class AuthAccountRepositoryRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.state.redis = MagicMock()
        app.include_router(routes_auth.router, prefix="/api")
        self.repository = MagicMock()
        app.dependency_overrides[get_user_account_repository] = (
            lambda: self.repository
        )
        self.client = TestClient(app)

    def test_register_uses_repository_and_consumes_otp_after_insert(self) -> None:
        events: list[str] = []
        email_service = MagicMock()
        email_service.verify_otp = AsyncMock(return_value=True)
        email_service.consume_otp = AsyncMock(
            side_effect=lambda *args, **kwargs: events.append("consume")
        )
        self.repository.get_user_by_email.return_value = None
        self.repository.create_user_with_email.side_effect = (
            lambda *args, **kwargs: events.append("insert") or 42
        )

        with patch.object(
            routes_auth,
            "_get_email_service",
            return_value=email_service,
        ):
            response = self.client.post(
                "/api/auth/register",
                json={
                    "email": "reader@example.com",
                    "email_code": "123456",
                    "password": "Str0ng!Pass",
                    "username": "读者甲",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"detail": "注册成功", "user_id": 42})
        args = self.repository.create_user_with_email.call_args.args
        self.assertEqual(args[0], "reader@example.com")
        self.assertNotEqual(args[1], "Str0ng!Pass")
        self.assertEqual(args[2:], ("user", "读者甲"))
        self.assertEqual(events, ["insert", "consume"])

    def test_register_duplicate_preserves_conflict_without_consuming_otp(self) -> None:
        email_service = MagicMock()
        email_service.verify_otp = AsyncMock(return_value=True)
        email_service.consume_otp = AsyncMock()
        self.repository.get_user_by_email.return_value = {"id": 42}

        with patch.object(
            routes_auth,
            "_get_email_service",
            return_value=email_service,
        ):
            response = self.client.post(
                "/api/auth/register",
                json={
                    "email": "reader@example.com",
                    "email_code": "123456",
                    "password": "Str0ng!Pass",
                    "username": "读者甲",
                },
            )

        self.assertEqual(response.status_code, 409)
        # 409 保持中性文案，明确引导登录或找回密码
        self.assertEqual(response.json(), {"detail": "注册未完成，请尝试登录；如忘记密码，请通过“忘记密码”重置后登录"})
        self.repository.create_user_with_email.assert_not_called()
        email_service.consume_otp.assert_not_awaited()

    def test_login_preserves_failure_and_jwt_claims(self) -> None:
        self.repository.get_user_by_email.return_value = {
            "id": 42,
            "email": "reader@example.com",
            "role": "user",
            "hashed_password": hash_password("abcdef"),
            "pwd_ver": 2,
        }

        with patch.object(
            routes_auth,
            "create_access_token",
            return_value="signed-token",
        ) as create_token:
            response = self.client.post(
                "/api/auth/login",
                json={"email": "reader@example.com", "password": "abcdef"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "access_token": "signed-token",
                "token_type": "bearer",
                "role": "user",
                "password_change_required": False,
            },
        )
        # 登录响应携带令牌：必须禁止任何中间缓存存储
        self.assertEqual(response.headers["cache-control"], "no-store")
        create_token.assert_called_once_with(
            {
                "user_id": 42,
                "role": "user",
                "email": "reader@example.com",
                "pwd_ver": 2,
            }
        )

        self.repository.get_user_by_email.return_value = None
        missing = self.client.post(
            "/api/auth/login",
            json={"email": "missing@example.com", "password": "abcdef"},
        )
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json(), {"detail": "邮箱或密码错误"})


if __name__ == "__main__":
    unittest.main()
