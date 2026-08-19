"""会员档位（0045）契约测试。

覆盖三处行为：

- ``normalize_membership_tier`` 的 fail-closed 归一化（未知值一律 free）；
- ``RequireUser`` 以库内 ``membership_tier`` 为准的身份透传（缺列/脏值回退 free）；
- ``POST /ops/membership/grant`` 运营授予端点的权限与响应契约；
- ``GET /auth/me`` 响应携带 ``membership_tier``。
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_auth, routes_ops
from backend.app.api.dependencies import get_user_account_repository
from backend.app.core.auth import RequireAdmin, RequireUser, create_access_token
from backend.app.services.membership.tiers import (
    MEMBERSHIP_TIER_FREE,
    MEMBERSHIP_TIER_MEMBER,
    normalize_membership_tier,
    resolve_effective_tier,
)


class FakeUserAccountRepository:
    """内存用户仓储：按 id/email 查记录，记录 set_membership_tier 调用。"""

    def __init__(self) -> None:
        self.records_by_id: dict[int, dict[str, Any]] = {}
        self.set_calls: list[tuple[int, str, Any]] = []

    def add_user(self, record: dict[str, Any]) -> None:
        self.records_by_id[int(record["id"])] = record

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        return self.records_by_id.get(user_id)

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        for record in self.records_by_id.values():
            if record.get("email") == email:
                return record
        return None

    def set_membership_tier(
        self,
        *,
        user_id: int,
        tier: str,
        expires_at: Any = None,
    ) -> int:
        self.set_calls.append((user_id, tier, expires_at))
        record = self.records_by_id.get(user_id)
        if record is None:
            return 0
        record["membership_tier"] = tier
        record["membership_expires_at"] = expires_at
        return 1


def _bearer(claims: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(claims)}"}


class MembershipTierNormalizationTests(unittest.TestCase):
    def test_known_tiers_pass_through(self) -> None:
        self.assertEqual(normalize_membership_tier("free"), MEMBERSHIP_TIER_FREE)
        self.assertEqual(normalize_membership_tier("member"), MEMBERSHIP_TIER_MEMBER)

    def test_unknown_and_empty_values_fall_back_to_free(self) -> None:
        for value in (None, "", "vip", "MEMBER", b"member", 1, ["member"]):
            with self.subTest(value=value):
                self.assertEqual(
                    normalize_membership_tier(value), MEMBERSHIP_TIER_FREE
                )


class EffectiveTierResolutionTests(unittest.TestCase):
    """生效档位（0048）：member 过期按 free，NULL/未来到期保持 member。"""

    def test_member_without_expiry_stays_member(self) -> None:
        self.assertEqual(resolve_effective_tier("member", None), "member")
        self.assertEqual(resolve_effective_tier("member"), "member")

    def test_member_with_future_expiry_stays_member(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(days=30)
        self.assertEqual(resolve_effective_tier("member", future), "member")
        # ISO 串链路（MCP token metadata / JSON）同口径
        self.assertEqual(resolve_effective_tier("member", future.isoformat()), "member")

    def test_member_with_past_expiry_falls_back_to_free(self) -> None:
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.assertEqual(resolve_effective_tier("member", past), "free")
        self.assertEqual(resolve_effective_tier("member", past.isoformat()), "free")

    def test_naive_datetime_is_interpreted_as_utc(self) -> None:
        past_naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        self.assertEqual(resolve_effective_tier("member", past_naive), "free")

    def test_free_and_unknown_tiers_ignore_expiry(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(days=30)
        self.assertEqual(resolve_effective_tier("free", future), "free")
        self.assertEqual(resolve_effective_tier("vip", future), "free")
        self.assertEqual(resolve_effective_tier(None, None), "free")

    def test_unparseable_expiry_is_treated_as_no_expiry(self) -> None:
        # 脏数据只影响到期判定，档位本身仍由 normalize fail-closed 兜底
        self.assertEqual(resolve_effective_tier("member", "not-a-date"), "member")
        self.assertEqual(resolve_effective_tier("member", 12345), "member")


class RequireUserMembershipTierTests(unittest.TestCase):
    """身份透传：membership_tier 以库内为准，缺列/脏值 fail-closed 回退 free。"""

    def setUp(self) -> None:
        self.repository = FakeUserAccountRepository()
        app = FastAPI()
        app.state.application_repositories = SimpleNamespace(users=self.repository)

        @app.get("/api/profile")
        async def profile(user: dict[str, Any] = Depends(RequireUser)) -> dict[str, Any]:
            return {"membership_tier": user.get("membership_tier")}

        self.client = TestClient(app)

    def _get_tier(self, user_id: int) -> str:
        response = self.client.get(
            "/api/profile",
            headers=_bearer({"user_id": user_id, "role": "user"}),
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["membership_tier"]

    def test_member_tier_is_propagated_from_database(self) -> None:
        self.repository.add_user({"id": 1, "role": "user", "membership_tier": "member"})

        self.assertEqual(self._get_tier(1), "member")

    def test_missing_column_falls_back_to_free(self) -> None:
        # 迁移未应用的热重启窗口：记录缺列（.get → None）按 free 处理
        self.repository.add_user({"id": 2, "role": "user"})

        self.assertEqual(self._get_tier(2), "free")

    def test_dirty_value_falls_back_to_free(self) -> None:
        self.repository.add_user({"id": 3, "role": "user", "membership_tier": "vip"})

        self.assertEqual(self._get_tier(3), "free")

    def test_expired_member_falls_back_to_free(self) -> None:
        # 0048：库内 member 但到期时间已过，生效档位 fail-closed 按 free
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        self.repository.add_user(
            {
                "id": 4,
                "role": "user",
                "membership_tier": "member",
                "membership_expires_at": past,
            }
        )

        self.assertEqual(self._get_tier(4), "free")

    def test_unexpired_member_stays_member(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(days=30)
        self.repository.add_user(
            {
                "id": 5,
                "role": "user",
                "membership_tier": "member",
                "membership_expires_at": future,
            }
        )

        self.assertEqual(self._get_tier(5), "member")


class MembershipGrantRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeUserAccountRepository()
        self.app = FastAPI()
        self.app.include_router(routes_ops.router, prefix="/api")
        self.app.state.application_repositories = SimpleNamespace(
            users=self.repository
        )
        self.app.dependency_overrides[get_user_account_repository] = (
            lambda: self.repository
        )
        self.client = TestClient(self.app)

    def _grant_as_admin(self) -> None:
        self.app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}

    def test_admin_grants_member_tier(self) -> None:
        self._grant_as_admin()
        self.repository.add_user(
            {"id": 7, "email": "member@example.com", "role": "user"}
        )

        response = self.client.post(
            "/api/ops/membership/grant",
            json={"email": "member@example.com", "tier": "member"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "user_id": 7,
                "email": "member@example.com",
                "membership_tier": "member",
                "membership_expires_at": None,
                "revoked": False,
            },
        )
        self.assertEqual(self.repository.set_calls, [(7, "member", None)])

    def test_admin_grants_member_tier_with_expiry(self) -> None:
        self._grant_as_admin()
        self.repository.add_user(
            {"id": 12, "email": "member@example.com", "role": "user"}
        )

        response = self.client.post(
            "/api/ops/membership/grant",
            json={
                "email": "member@example.com",
                "tier": "member",
                "expires_at": "2027-01-01T23:59:59+08:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["membership_tier"], "member")
        # 带时区输入按原瞬间回显（UTC 归一后同一时刻）
        self.assertEqual(
            datetime.fromisoformat(body["membership_expires_at"]),
            datetime(2027, 1, 1, 23, 59, 59, tzinfo=timezone(timedelta(hours=8))),
        )
        stored = self.repository.records_by_id[12]
        self.assertEqual(stored["membership_tier"], "member")
        self.assertEqual(
            stored["membership_expires_at"],
            datetime(2027, 1, 1, 23, 59, 59, tzinfo=timezone(timedelta(hours=8))),
        )

    def test_admin_revokes_membership_with_free_tier(self) -> None:
        self._grant_as_admin()
        self.repository.add_user(
            {
                "id": 8,
                "email": "member@example.com",
                "role": "user",
                "membership_tier": "member",
            }
        )

        response = self.client.post(
            "/api/ops/membership/grant",
            json={"email": "member@example.com", "tier": "free"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["membership_tier"], "free")
        self.assertIsNone(response.json()["membership_expires_at"])
        self.assertTrue(response.json()["revoked"])
        self.assertEqual(self.repository.set_calls, [(8, "free", None)])

    def test_revoke_clears_existing_expiry(self) -> None:
        # 吊销语义：即使请求带了 expires_at，free 档也强制清空到期时间
        self._grant_as_admin()
        self.repository.add_user(
            {
                "id": 13,
                "email": "member@example.com",
                "role": "user",
                "membership_tier": "member",
                "membership_expires_at": datetime.now(timezone.utc) + timedelta(days=10),
            }
        )

        response = self.client.post(
            "/api/ops/membership/grant",
            json={
                "email": "member@example.com",
                "tier": "free",
                "expires_at": "2027-01-01T00:00:00+00:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["membership_expires_at"])
        self.assertIsNone(self.repository.records_by_id[13]["membership_expires_at"])

    def test_email_is_normalized_before_lookup(self) -> None:
        self._grant_as_admin()
        self.repository.add_user(
            {"id": 9, "email": "member@example.com", "role": "user"}
        )

        response = self.client.post(
            "/api/ops/membership/grant",
            json={"email": "  Member@Example.COM ", "tier": "member"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.repository.set_calls, [(9, "member", None)])

    def test_unknown_email_returns_404(self) -> None:
        self._grant_as_admin()

        response = self.client.post(
            "/api/ops/membership/grant",
            json={"email": "ghost@example.com", "tier": "member"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.repository.set_calls, [])

    def test_invalid_tier_is_rejected_with_422(self) -> None:
        self._grant_as_admin()
        self.repository.add_user(
            {"id": 10, "email": "member@example.com", "role": "user"}
        )

        response = self.client.post(
            "/api/ops/membership/grant",
            json={"email": "member@example.com", "tier": "vip"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.repository.set_calls, [])

    def test_non_admin_is_forbidden(self) -> None:
        # 不覆盖 RequireAdmin：真实依赖链 RequireUser（查库）→ 角色非 admin 即 403
        self.repository.add_user({"id": 11, "role": "user"})

        response = self.client.post(
            "/api/ops/membership/grant",
            json={"email": "member@example.com", "tier": "member"},
            headers=_bearer({"user_id": 11, "role": "user"}),
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.repository.set_calls, [])


class AuthMeMembershipTierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeUserAccountRepository()
        app = FastAPI()
        app.include_router(routes_auth.router, prefix="/api")
        app.state.application_repositories = SimpleNamespace(users=self.repository)
        self.client = TestClient(app)

    def test_auth_me_includes_membership_tier(self) -> None:
        self.repository.add_user(
            {
                "id": 21,
                "email": "member@example.com",
                "role": "user",
                "membership_tier": "member",
            }
        )

        response = self.client.get(
            "/api/auth/me",
            headers=_bearer(
                {"user_id": 21, "role": "user", "email": "member@example.com"}
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["membership_tier"], "member")

    def test_auth_me_exposes_membership_expiry(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(days=30)
        self.repository.add_user(
            {
                "id": 23,
                "email": "member@example.com",
                "role": "user",
                "membership_tier": "member",
                "membership_expires_at": future,
            }
        )

        response = self.client.get(
            "/api/auth/me",
            headers=_bearer(
                {"user_id": 23, "role": "user", "email": "member@example.com"}
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["membership_expires_at"], future.isoformat()
        )

    def test_auth_me_expired_member_reports_free(self) -> None:
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        self.repository.add_user(
            {
                "id": 24,
                "email": "member@example.com",
                "role": "user",
                "membership_tier": "member",
                "membership_expires_at": past,
            }
        )

        response = self.client.get(
            "/api/auth/me",
            headers=_bearer(
                {"user_id": 24, "role": "user", "email": "member@example.com"}
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["membership_tier"], "free")

    def test_auth_me_defaults_to_free_when_column_missing(self) -> None:
        self.repository.add_user(
            {"id": 22, "email": "plain@example.com", "role": "user"}
        )

        response = self.client.get(
            "/api/auth/me",
            headers=_bearer(
                {"user_id": 22, "role": "user", "email": "plain@example.com"}
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["membership_tier"], "free")


if __name__ == "__main__":
    unittest.main()
