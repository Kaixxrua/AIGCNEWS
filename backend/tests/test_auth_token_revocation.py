from __future__ import annotations

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app.api import routes_ui_library
from backend.app.core.auth import (
    OptionalUser,
    RequireAdmin,
    RequireUser,
    create_access_token,
    get_user_identity_repository,
)
from backend.app.repositories.postgres_user_account_repository import (
    PostgresUserAccountRepository,
)


class FakeUserAccountRepository:
    """按 id 返回用户记录的内存仓储，并记录每次主键查询。"""

    def __init__(self) -> None:
        self.records: dict[int, dict[str, Any] | None] = {}
        self.queries: list[int] = []

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        self.queries.append(user_id)
        return self.records.get(user_id)


def _build_app(repository: FakeUserAccountRepository) -> FastAPI:
    app = FastAPI()
    app.state.application_repositories = SimpleNamespace(users=repository)

    @app.get("/api/profile")
    async def profile(user: dict[str, Any] = Depends(RequireUser)) -> dict[str, Any]:
        return {"user_id": user.get("user_id"), "role": user.get("role")}

    @app.get("/api/admin-only")
    async def admin_only(
        user: dict[str, Any] = Depends(RequireAdmin),
    ) -> dict[str, Any]:
        return {"role": user.get("role")}

    return app


def _bearer(claims: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(claims)}"}


class TokenRevocationTests(unittest.TestCase):
    """JWT 服务端撤销与角色以库为准的契约测试。"""

    def setUp(self) -> None:
        self.repository = FakeUserAccountRepository()
        self.app = _build_app(self.repository)
        self.client = TestClient(self.app)

    def test_existing_user_token_passes_and_role_comes_from_database(self) -> None:
        self.repository.records[7] = {"id": 7, "role": "user"}

        response = self.client.get(
            "/api/profile",
            headers=_bearer({"user_id": 7, "role": "user", "email": "r@example.com"}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"user_id": 7, "role": "user"})
        self.assertEqual(self.repository.queries, [7])

    def test_deleted_user_token_is_rejected(self) -> None:
        # 用户已删号：库中查无记录，token 剩余有效期内也必须拒绝
        response = self.client.get(
            "/api/profile",
            headers=_bearer({"user_id": 404, "role": "user"}),
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "账号不存在或已被禁用"})
        self.assertEqual(response.headers["www-authenticate"], "Bearer")
        self.assertEqual(self.repository.queries, [404])

    def test_disabled_user_token_is_rejected(self) -> None:
        self.repository.records[8] = {"id": 8, "role": "user", "disabled": True}

        response = self.client.get(
            "/api/profile",
            headers=_bearer({"user_id": 8, "role": "user"}),
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "账号不存在或已被禁用"})

    def test_token_without_valid_user_id_is_rejected_before_query(self) -> None:
        response = self.client.get("/api/profile", headers=_bearer({"role": "user"}))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "用户身份无效"})
        self.assertEqual(self.repository.queries, [])

    def test_stale_pwd_ver_token_is_rejected_after_password_change(self) -> None:
        # 改密使库内 pwd_ver 递增：签发时的旧声明失配，token 立即失效（AUTH-B）
        self.repository.records[12] = {"id": 12, "role": "user", "pwd_ver": 2}

        response = self.client.get(
            "/api/profile",
            headers=_bearer({"user_id": 12, "role": "user", "pwd_ver": 1}),
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "登录状态已失效，请重新登录"})
        self.assertEqual(response.headers["www-authenticate"], "Bearer")

    def test_legacy_token_without_pwd_ver_is_rejected_once_column_exists(self) -> None:
        # 升级前签发的历史 JWT 没有 pwd_ver 声明：库内已有版本号时一律失效，
        # 强制用户重新登录一次换取带声明的新 token
        self.repository.records[13] = {"id": 13, "role": "user", "pwd_ver": 1}

        response = self.client.get(
            "/api/profile",
            headers=_bearer({"user_id": 13, "role": "user"}),
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "登录状态已失效，请重新登录"})

    def test_matching_pwd_ver_token_passes(self) -> None:
        self.repository.records[14] = {"id": 14, "role": "user", "pwd_ver": 5}

        response = self.client.get(
            "/api/profile",
            headers=_bearer({"user_id": 14, "role": "user", "pwd_ver": 5}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"user_id": 14, "role": "user"})

    def test_record_without_pwd_ver_skips_comparison_for_unmigrated_schema(self) -> None:
        # 库内缺列（迁移未应用）时跳过比对：不阻断升级窗口期的存量会话
        self.repository.records[15] = {"id": 15, "role": "user"}

        response = self.client.get(
            "/api/profile",
            headers=_bearer({"user_id": 15, "role": "user"}),
        )

        self.assertEqual(response.status_code, 200)

    def test_downgraded_admin_loses_admin_access_immediately(self) -> None:
        # token 签发时是 admin，库中已降级为 user：管理端点 403，普通端点放行且角色为 user
        self.repository.records[9] = {"id": 9, "role": "user"}
        headers = _bearer({"user_id": 9, "role": "admin"})

        admin_response = self.client.get("/api/admin-only", headers=headers)
        user_response = self.client.get("/api/profile", headers=headers)

        self.assertEqual(admin_response.status_code, 403)
        self.assertEqual(admin_response.json(), {"detail": "权限不足，需要管理员角色"})
        self.assertEqual(user_response.status_code, 200)
        self.assertEqual(user_response.json(), {"user_id": 9, "role": "user"})

    def test_promoted_admin_gains_admin_access_without_relogin(self) -> None:
        # 角色以库为准是双向的：库中已升级为 admin 时无需重新签发 token
        self.repository.records[10] = {"id": 10, "role": "admin"}

        response = self.client.get(
            "/api/admin-only",
            headers=_bearer({"user_id": 10, "role": "user"}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"role": "admin"})

    def test_admin_in_database_keeps_admin_access(self) -> None:
        self.repository.records[11] = {"id": 11, "role": "admin"}

        response = self.client.get(
            "/api/admin-only",
            headers=_bearer({"user_id": 11, "role": "admin"}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"role": "admin"})

    def test_missing_authorization_header_stays_401_without_repositories(self) -> None:
        # 未携带 Bearer 头时不得触碰 app.state（隔离路由测试没有装配仓储）
        bare = FastAPI()

        @bare.get("/api/profile")
        async def profile(user: dict[str, Any] = Depends(RequireUser)) -> dict[str, Any]:
            return user

        response = TestClient(bare).get("/api/profile")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "缺少 Authorization 头"})

    def test_bearer_token_without_configured_repositories_fails_closed(self) -> None:
        # 生产装配缺失时不得回退为信任 token：拒绝服务而非放行
        bare = FastAPI()

        @bare.get("/api/profile")
        async def profile(user: dict[str, Any] = Depends(RequireUser)) -> dict[str, Any]:
            return user

        client = TestClient(bare, raise_server_exceptions=False)
        response = client.get(
            "/api/profile",
            headers=_bearer({"user_id": 7, "role": "user"}),
        )

        self.assertEqual(response.status_code, 500)

    def test_require_user_override_bypasses_database_lookup(self) -> None:
        # 既有测试契约：dependency_overrides 覆盖 RequireUser 后无需任何仓储
        bare = FastAPI()

        @bare.get("/api/profile")
        async def profile(user: dict[str, Any] = Depends(RequireUser)) -> dict[str, Any]:
            return {"user_id": user.get("user_id"), "role": user.get("role")}

        bare.dependency_overrides[RequireUser] = lambda: {
            "user_id": 3,
            "role": "user",
        }

        response = TestClient(bare).get("/api/profile")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"user_id": 3, "role": "user"})

    def test_identity_repository_dependency_can_be_overridden(self) -> None:
        # 细粒度覆盖：只替换仓储依赖，保留真实 JWT 解码与核验逻辑
        bare = FastAPI()
        repository = FakeUserAccountRepository()
        repository.records[5] = {"id": 5, "role": "admin"}

        @bare.get("/api/admin-only")
        async def admin_only(
            user: dict[str, Any] = Depends(RequireAdmin),
        ) -> dict[str, Any]:
            return {"role": user.get("role")}

        bare.dependency_overrides[get_user_identity_repository] = lambda: repository

        response = TestClient(bare).get(
            "/api/admin-only",
            headers=_bearer({"user_id": 5, "role": "admin"}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"role": "admin"})
        self.assertEqual(repository.queries, [5])


class OptionalTokenRevocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.users = FakeUserAccountRepository()
        self.users.records[7] = {"id": 7, "role": "user", "pwd_ver": 1}
        self.app = FastAPI()
        self.likes = MagicMock()
        self.likes.engagement.side_effect = lambda user_id, *_: [{"template_id": "test", "liked": user_id == 7}]
        self.app.state.application_repositories = SimpleNamespace(users=self.users, ui_library=self.likes)
        self.app.include_router(routes_ui_library.router, prefix="/api")

        @self.app.get("/optional")
        async def optional(user: dict | None = Depends(OptionalUser)):
            return user

        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.headers = _bearer({"user_id": 7, "role": "admin", "pwd_ver": 1, "membership_tier": "member"})

    def test_current_identity_personalizes_using_live_role(self) -> None:
        response = self.client.get("/optional", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "user")
        self.assertEqual(response.json()["membership_tier"], "member")
        response = self.client.get("/api/ui-library/engagement", headers=self.headers)
        self.assertTrue(response.json()["items"][0]["liked"])

    def test_password_change_disable_and_delete_remove_personalization(self) -> None:
        # Reuse the same issued token before and after each independent change.
        for revoked_record in (
            {"id": 7, "role": "user", "pwd_ver": 2},
            {"id": 7, "role": "user", "pwd_ver": 1, "disabled": True},
            None,
        ):
            with self.subTest(record=revoked_record):
                self.users.records[7] = {"id": 7, "role": "user", "pwd_ver": 1}
                before = self.client.get("/api/ui-library/engagement", headers=self.headers)
                self.assertTrue(before.json()["items"][0]["liked"])
                self.users.records[7] = revoked_record
                after = self.client.get("/api/ui-library/engagement", headers=self.headers)
                self.assertEqual(after.status_code, 200)
                self.assertFalse(after.json()["items"][0]["liked"])
                self.assertIsNone(self.likes.engagement.call_args.args[0])

    def test_missing_password_version_is_anonymous(self) -> None:
        response = self.client.get("/optional", headers=_bearer({"user_id": 7, "role": "user"}))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())

    def test_unmigrated_record_without_password_version_keeps_required_auth_compatibility(self) -> None:
        self.users.records[7] = {"id": 7, "role": "user"}
        response = self.client.get("/optional", headers=_bearer({"user_id": 7}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user_id"], 7)

    def test_absent_and_invalid_credentials_need_no_identity_repository(self) -> None:
        del self.app.state.application_repositories
        for headers in ({}, {"Authorization": "Basic ignored"}, {"Authorization": "Bearer invalid"}):
            with self.subTest(headers=headers):
                response = self.client.get("/optional", headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.json())
        self.assertEqual(self.users.queries, [])

    def test_valid_credentials_require_wiring_and_database_availability(self) -> None:
        del self.app.state.application_repositories
        self.assertEqual(self.client.get("/optional", headers=self.headers).status_code, 500)
        failed_users = MagicMock()
        failed_users.get_user_by_id.side_effect = RuntimeError("database unavailable")
        self.app.dependency_overrides[get_user_identity_repository] = lambda: failed_users
        self.assertEqual(self.client.get("/optional", headers=self.headers).status_code, 500)
        failed_users.get_user_by_id.side_effect = HTTPException(503, "database unavailable")
        self.assertEqual(self.client.get("/optional", headers=self.headers).status_code, 503)

    def test_optional_dependency_override_still_bypasses_identity_lookup(self) -> None:
        del self.app.state.application_repositories
        self.app.dependency_overrides[OptionalUser] = lambda: {"user_id": 9, "role": "user"}
        response = self.client.get("/optional")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user_id"], 9)


class _FakeDatabase:
    """PostgresUserAccountRepository 的最小数据库替身（复用配置仓储测试模式）。"""

    def __init__(self, cursor: MagicMock) -> None:
        self.cursor = cursor
        self.connection = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        self.connection.cursor.return_value = cursor_context

    @contextmanager
    def transaction(self):
        yield self.connection


class PostgresGetUserByIdTests(unittest.TestCase):
    def test_get_user_by_id_queries_primary_key_without_password_hash(self) -> None:
        cursor = MagicMock()
        cursor.fetchone.return_value = {"id": 7, "role": "admin"}
        repository = PostgresUserAccountRepository(_FakeDatabase(cursor))

        record = repository.get_user_by_id(7)

        self.assertEqual(record, {"id": 7, "role": "admin"})
        sql, params = cursor.execute.call_args.args
        self.assertIn("FROM users", sql)
        self.assertIn("WHERE id = %s", sql)
        self.assertNotIn("hashed_password", sql)
        # 身份核验路径必须投影 disabled 与 pwd_ver（禁用/改密即撤销的判定输入）
        self.assertIn("disabled", sql)
        self.assertIn("pwd_ver", sql)
        self.assertEqual(params, (7,))

    def test_get_user_by_id_returns_none_for_unknown_id(self) -> None:
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        repository = PostgresUserAccountRepository(_FakeDatabase(cursor))

        self.assertIsNone(repository.get_user_by_id(999))


if __name__ == "__main__":
    unittest.main()
