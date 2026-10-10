from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_auth
from backend.app.api.dependencies import (
    get_oauth_identity_repository,
    get_user_account_repository,
)
from backend.app.core.auth import (
    create_access_token,
    get_user_identity_repository,
    hash_password,
)
from backend.app.services.email_service import (
    OtpDeliveryUnavailableError,
    OtpSendRateLimitedError,
)


class FakeUserAccountRepository:
    """按 id / email 双索引的内存仓储，记录写操作事件。"""

    def __init__(self) -> None:
        self.events: list[tuple[Any, ...]] = []
        self.users_by_email: dict[str, dict[str, Any]] = {}
        self.affected_rows = 1

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        for user in self.users_by_email.values():
            if user["id"] == user_id:
                return user
        return None

    def list_identities_for_user(self, user_id: int) -> list[dict[str, Any]]:
        return []

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        self.events.append(("get_user_by_email", email))
        return self.users_by_email.get(email)

    def update_user_password(
        self,
        *,
        user_id: int,
        email: str,
        hashed_password: str,
    ) -> int:
        self.events.append(("update_user_password", user_id, email, hashed_password))
        if self.affected_rows == 1:
            for user in self.users_by_email.values():
                if user["id"] == user_id:
                    user["pwd_ver"] = int(user.get("pwd_ver") or 1) + 1
                    break
        return self.affected_rows


def _bearer(claims: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(claims)}"}


def _fake_email_service(*, verified: bool = True) -> MagicMock:
    service = MagicMock()
    service.send_otp = AsyncMock()
    service.verify_otp = AsyncMock(return_value=verified)
    service.consume_otp = AsyncMock()
    return service


class ChangePasswordRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(routes_auth.router, prefix="/api")
        self.repository = FakeUserAccountRepository()
        app.dependency_overrides[get_user_account_repository] = (
            lambda: self.repository
        )
        app.dependency_overrides[get_oauth_identity_repository] = (
            lambda: self.repository
        )
        app.dependency_overrides[get_user_identity_repository] = (
            lambda: self.repository
        )
        self.client = TestClient(app)
        self.repository.users_by_email["reader@example.com"] = {
            "id": 7,
            "email": "reader@example.com",
            "role": "user",
            "hashed_password": hash_password("current-secret"),
        }

    def _headers(self) -> dict[str, str]:
        return _bearer({"user_id": 7, "role": "user", "email": "reader@example.com"})

    def test_change_password_success_updates_hash_and_hides_secrets(self) -> None:
        email_service = _fake_email_service(verified=True)

        with patch.object(
            routes_auth, "_get_email_service", return_value=email_service
        ):
            response = self.client.post(
                "/api/auth/me/password",
                headers=self._headers(),
                json={
                    "email_code": "123456",
                    "new_password": "replacement-secret",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["token_type"], "bearer")
        self.assertIs(payload["changed"], True)
        self.assertTrue(payload["access_token"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(
            self.repository.events,
            [("update_user_password", 7, "reader@example.com", unittest.mock.ANY)],
        )
        update = self.repository.events[0]
        updated_hash = update[3]
        self.assertNotIn("replacement-secret", updated_hash)
        email_service.verify_otp.assert_awaited_once_with(
            "reader@example.com", "123456", consume=True, purpose="password_change"
        )
        email_service.consume_otp.assert_not_awaited()
        serialized = response.content.decode()
        self.assertNotIn("replacement-secret", serialized)
        self.assertNotIn("123456", serialized)
        self.assertNotIn(updated_hash, serialized)

    def test_change_password_rejects_invalid_otp(self) -> None:
        email_service = _fake_email_service(verified=False)

        with patch.object(
            routes_auth, "_get_email_service", return_value=email_service
        ):
            response = self.client.post(
                "/api/auth/me/password",
                headers=self._headers(),
                json={
                    "email_code": "000000",
                    "new_password": "replacement-secret",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "验证码错误或已过期"})
        self.assertNotIn(
            "update_user_password",
            [event[0] for event in self.repository.events],
        )
        email_service.consume_otp.assert_not_awaited()

    def test_change_password_requires_exactly_one_updated_row(self) -> None:
        self.repository.affected_rows = 0
        email_service = _fake_email_service(verified=True)

        with patch.object(
            routes_auth, "_get_email_service", return_value=email_service
        ):
            response = self.client.post(
                "/api/auth/me/password",
                headers=self._headers(),
                json={
                    "email_code": "123456",
                    "new_password": "replacement-secret",
                },
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "密码修改失败，请稍后重试"})
        email_service.consume_otp.assert_not_awaited()

    def test_change_password_requires_authentication(self) -> None:
        response = self.client.post(
            "/api/auth/me/password",
            json={
                "email_code": "123456",
                "new_password": "replacement-secret",
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.repository.events, [])

    def test_change_password_enforces_new_password_policy(self) -> None:
        response = self.client.post(
            "/api/auth/me/password",
            headers=self._headers(),
            json={"email_code": "123456", "new_password": "12345"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.repository.events, [])

    def test_change_password_enforces_email_code_format(self) -> None:
        response = self.client.post(
            "/api/auth/me/password",
            headers=self._headers(),
            json={"email_code": "abcde", "new_password": "replacement-secret"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.repository.events, [])

    def test_change_password_uses_user_id_without_email_claim(self) -> None:
        email_service = _fake_email_service(verified=True)
        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self.client.post(
                "/api/auth/me/password",
                headers=_bearer({"user_id": 7, "role": "user"}),
                json={
                    "email_code": "123456",
                    "new_password": "replacement-secret",
                },
            )

        self.assertEqual(response.status_code, 200)
        email_service.verify_otp.assert_awaited_once_with(
            "reader@example.com", "123456", consume=True, purpose="password_change"
        )

    def test_change_password_ignores_stale_email_claim(self) -> None:
        email_service = _fake_email_service(verified=True)
        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self.client.post(
                "/api/auth/me/password",
                headers=_bearer({"user_id": 7, "role": "user", "email": "old@example.com"}),
                json={"email_code": "123456", "new_password": "replacement-secret"},
            )

        self.assertEqual(response.status_code, 200)
        email_service.verify_otp.assert_awaited_once_with(
            "reader@example.com", "123456", consume=True, purpose="password_change"
        )


class SendChangePasswordOtpRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(routes_auth.router, prefix="/api")
        self.repository = FakeUserAccountRepository()
        app.dependency_overrides[get_user_account_repository] = (
            lambda: self.repository
        )
        app.dependency_overrides[get_oauth_identity_repository] = (
            lambda: self.repository
        )
        app.dependency_overrides[get_user_identity_repository] = (
            lambda: self.repository
        )
        self.client = TestClient(app)
        self.repository.users_by_email["reader@example.com"] = {
            "id": 7,
            "email": "reader@example.com",
            "role": "user",
            "hashed_password": hash_password("current-secret"),
        }

    def _headers(self) -> dict[str, str]:
        return _bearer({"user_id": 7, "role": "user", "email": "reader@example.com"})

    def test_send_otp_delivers_to_current_account_email(self) -> None:
        email_service = _fake_email_service()

        with patch.object(
            routes_auth, "_get_email_service", return_value=email_service
        ):
            response = self.client.post(
                "/api/auth/me/send-password-change-otp",
                headers=self._headers(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"detail": "验证码已发送至当前账号邮箱"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        email_service.send_otp.assert_awaited_once_with(
            "reader@example.com", purpose="password_change", deliver=True
        )

    def test_send_otp_requires_authentication(self) -> None:
        response = self.client.post("/api/auth/me/send-password-change-otp")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.repository.events, [])

    def test_send_otp_uses_user_id_without_email_claim(self) -> None:
        email_service = _fake_email_service()
        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self.client.post(
                "/api/auth/me/send-password-change-otp",
                headers=_bearer({"user_id": 7, "role": "user"}),
            )

        self.assertEqual(response.status_code, 200)
        email_service.send_otp.assert_awaited_once_with(
            "reader@example.com", purpose="password_change", deliver=True
        )

    def test_send_otp_ignores_stale_email_claim(self) -> None:
        email_service = _fake_email_service()
        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self.client.post(
                "/api/auth/me/send-password-change-otp",
                headers=_bearer({"user_id": 7, "role": "user", "email": "old@example.com"}),
            )

        self.assertEqual(response.status_code, 200)
        email_service.send_otp.assert_awaited_once_with(
            "reader@example.com", purpose="password_change", deliver=True
        )

    def test_send_otp_maps_cooldown_to_429(self) -> None:
        email_service = _fake_email_service()
        email_service.send_otp = AsyncMock(
            side_effect=OtpSendRateLimitedError("请求过于频繁，请 60 秒后再试")
        )

        with patch.object(
            routes_auth, "_get_email_service", return_value=email_service
        ):
            response = self.client.post(
                "/api/auth/me/send-password-change-otp",
                headers=self._headers(),
            )

        self.assertEqual(response.status_code, 429)

    def test_send_otp_maps_delivery_unavailable_to_503(self) -> None:
        email_service = _fake_email_service()
        email_service.send_otp = AsyncMock(
            side_effect=OtpDeliveryUnavailableError("邮件服务暂不可用，请稍后重试")
        )

        with patch.object(
            routes_auth, "_get_email_service", return_value=email_service
        ):
            response = self.client.post(
                "/api/auth/me/send-password-change-otp",
                headers=self._headers(),
            )

        self.assertEqual(response.status_code, 503)


class DefaultAdminCredentialFlagTests(unittest.TestCase):
    """password_change_required 标志：仅种子默认邮箱 + 默认密码组合为真。"""

    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(routes_auth.router, prefix="/api")
        self.repository = FakeUserAccountRepository()
        app.dependency_overrides[get_user_account_repository] = (
            lambda: self.repository
        )
        app.dependency_overrides[get_oauth_identity_repository] = (
            lambda: self.repository
        )
        app.dependency_overrides[get_user_identity_repository] = (
            lambda: self.repository
        )
        self.client = TestClient(app)

    def _seed_default_admin(self, password: str = "admin123456") -> None:
        self.repository.users_by_email["admin@aigcnews.internal"] = {
            "id": 1,
            "email": "admin@aigcnews.internal",
            "role": "admin",
            "hashed_password": hash_password(password),
        }

    def test_login_with_default_credentials_flags_password_change(self) -> None:
        self._seed_default_admin()

        response = self.client.post(
            "/api/auth/login",
            json={"email": "admin@aigcnews.internal", "password": "admin123456"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()["password_change_required"], True)

    def test_login_with_rotated_password_clears_flag(self) -> None:
        self._seed_default_admin(password="rotated-secret")

        response = self.client.post(
            "/api/auth/login",
            json={"email": "admin@aigcnews.internal", "password": "rotated-secret"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()["password_change_required"], False)

    def test_custom_legacy_admin_warns_on_login_and_me_with_empty_bootstrap_password(self) -> None:
        email = "owner@example.com"
        self.repository.users_by_email[email] = {
            "id": 1, "email": email, "role": "admin",
            "hashed_password": hash_password("admin123456"),
        }
        with (
            patch.object(routes_auth.settings, "DEFAULT_ADMIN_EMAIL", email),
            patch.object(routes_auth.settings, "DEFAULT_ADMIN_PASSWORD", ""),
        ):
            logged_in = self.client.post(
                "/api/auth/login", json={"email": email, "password": "admin123456"},
            )
            self.assertEqual(logged_in.status_code, 200)
            self.assertIs(logged_in.json()["password_change_required"], True)
            profile = self.client.get(
                "/api/auth/me", headers={"Authorization": f"Bearer {logged_in.json()['access_token']}"},
            )
            self.assertEqual(profile.status_code, 200)
            self.assertIs(profile.json()["password_change_required"], True)

    def test_me_flags_default_password_from_stored_hash(self) -> None:
        self._seed_default_admin()

        response = self.client.get(
            "/api/auth/me",
            headers=_bearer(
                {"user_id": 1, "role": "admin", "email": "admin@aigcnews.internal"}
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()["password_change_required"], True)

    def test_me_clears_flag_after_rotation(self) -> None:
        self._seed_default_admin(password="rotated-secret")

        response = self.client.get(
            "/api/auth/me",
            headers=_bearer(
                {"user_id": 1, "role": "admin", "email": "admin@aigcnews.internal"}
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()["password_change_required"], False)

    def test_me_short_circuits_regular_accounts_without_email_lookup(self) -> None:
        self.repository.users_by_email["reader@example.com"] = {
            "id": 7,
            "email": "reader@example.com",
            "role": "user",
            "hashed_password": hash_password("current-secret"),
        }

        response = self.client.get(
            "/api/auth/me",
            headers=_bearer({"user_id": 7, "role": "user", "email": "reader@example.com"}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()["password_change_required"], False)
        # 普通账号在取库前短路，不产生额外查询
        self.assertEqual(self.repository.events, [])


if __name__ == "__main__":
    unittest.main()
