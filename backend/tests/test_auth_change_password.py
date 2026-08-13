from __future__ import annotations

import unittest
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_auth
from backend.app.api.dependencies import get_user_account_repository
from backend.app.core.auth import (
    create_access_token,
    get_user_identity_repository,
    hash_password,
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
        return self.affected_rows


def _bearer(claims: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(claims)}"}


class ChangePasswordRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(routes_auth.router, prefix="/api")
        self.repository = FakeUserAccountRepository()
        app.dependency_overrides[get_user_account_repository] = (
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
        response = self.client.post(
            "/api/auth/me/password",
            headers=self._headers(),
            json={
                "current_password": "current-secret",
                "new_password": "replacement-secret",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"detail": "密码已修改"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        lookup, update = self.repository.events
        self.assertEqual(lookup, ("get_user_by_email", "reader@example.com"))
        self.assertEqual(update[:3], ("update_user_password", 7, "reader@example.com"))
        updated_hash = update[3]
        self.assertNotIn("replacement-secret", updated_hash)
        serialized = response.content.decode()
        self.assertNotIn("current-secret", serialized)
        self.assertNotIn("replacement-secret", serialized)
        self.assertNotIn(updated_hash, serialized)

    def test_change_password_rejects_wrong_current_password(self) -> None:
        response = self.client.post(
            "/api/auth/me/password",
            headers=self._headers(),
            json={
                "current_password": "wrong-secret",
                "new_password": "replacement-secret",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "当前密码错误"})
        self.assertNotIn(
            "update_user_password",
            [event[0] for event in self.repository.events],
        )

    def test_change_password_requires_exactly_one_updated_row(self) -> None:
        self.repository.affected_rows = 0

        response = self.client.post(
            "/api/auth/me/password",
            headers=self._headers(),
            json={
                "current_password": "current-secret",
                "new_password": "replacement-secret",
            },
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "密码修改失败，请稍后重试"})

    def test_change_password_requires_authentication(self) -> None:
        response = self.client.post(
            "/api/auth/me/password",
            json={
                "current_password": "current-secret",
                "new_password": "replacement-secret",
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.repository.events, [])

    def test_change_password_enforces_new_password_policy(self) -> None:
        response = self.client.post(
            "/api/auth/me/password",
            headers=self._headers(),
            json={"current_password": "current-secret", "new_password": "12345"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.repository.events, [])

    def test_change_password_rejects_token_without_email_claim(self) -> None:
        response = self.client.post(
            "/api/auth/me/password",
            headers=_bearer({"user_id": 7, "role": "user"}),
            json={
                "current_password": "current-secret",
                "new_password": "replacement-secret",
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "用户身份无效"})


class DefaultAdminCredentialFlagTests(unittest.TestCase):
    """password_change_required 标志：仅种子默认邮箱 + 默认密码组合为真。"""

    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(routes_auth.router, prefix="/api")
        self.repository = FakeUserAccountRepository()
        app.dependency_overrides[get_user_account_repository] = (
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
