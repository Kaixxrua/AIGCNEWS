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

CURRENT_EMAIL = "reader@example.com"
NEW_EMAIL = "newbox@example.com"
CURRENT_CODE = "111111"
NEW_CODE = "222222"


class FakeUserAccountRepository:
    """按 id / email 双索引的内存仓储；update_user_email 走快照条件语义。"""

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

    def update_user_email(
        self,
        *,
        user_id: int,
        current_email: str,
        new_email: str,
    ) -> int:
        self.events.append(("update_user_email", user_id, current_email, new_email))
        if self.affected_rows != 1:
            return self.affected_rows
        for key, user in list(self.users_by_email.items()):
            if user["id"] == user_id and (user.get("email") or "").lower() == current_email.lower():
                del self.users_by_email[key]
                user["email"] = new_email
                user["email_verified"] = True
                self.users_by_email[new_email] = user
                return 1
        return 0

    def list_identities_for_user(self, user_id: int) -> list[dict[str, Any]]:
        return []


def _bearer(claims: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(claims)}"}


def _fake_email_service(*, verified: bool = True) -> MagicMock:
    service = MagicMock()
    service.send_otp = AsyncMock()
    service.verify_otp = AsyncMock(return_value=verified)
    service.consume_otp = AsyncMock()
    return service


def _dual_code_email_service() -> MagicMock:
    """当前邮箱只认 CURRENT_CODE，新邮箱只认 NEW_CODE 的双码验真服务。"""
    service = MagicMock()
    service.send_otp = AsyncMock()

    async def _verify(email: str, code: str, consume: bool = True, *, purpose: str) -> bool:
        expected = CURRENT_CODE if email == CURRENT_EMAIL else NEW_CODE
        return code == expected

    service.verify_otp = AsyncMock(side_effect=_verify)
    service.consume_otp = AsyncMock()
    return service


class _EmailChangeRouteTestBase(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(routes_auth.router, prefix="/api")
        self.repository = FakeUserAccountRepository()
        app.dependency_overrides[get_user_account_repository] = lambda: self.repository
        app.dependency_overrides[get_oauth_identity_repository] = lambda: self.repository
        app.dependency_overrides[get_user_identity_repository] = lambda: self.repository
        self.client = TestClient(app)
        self.repository.users_by_email[CURRENT_EMAIL] = {
            "id": 7,
            "email": CURRENT_EMAIL,
            "role": "user",
            "hashed_password": hash_password("current-secret"),
        }

    def _headers(self) -> dict[str, str]:
        return _bearer({"user_id": 7, "role": "user", "email": CURRENT_EMAIL})


class SendEmailChangeCurrentOtpTests(_EmailChangeRouteTestBase):
    def test_delivers_to_database_current_email(self) -> None:
        email_service = _fake_email_service()

        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self.client.post(
                "/api/auth/me/email-change/send-current",
                headers=self._headers(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"detail": "验证码已发送至当前账号邮箱"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        email_service.send_otp.assert_awaited_once_with(
            CURRENT_EMAIL, purpose="email_change", deliver=True
        )

    def test_requires_authentication(self) -> None:
        response = self.client.post("/api/auth/me/email-change/send-current")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.repository.events, [])

    def test_rejects_account_without_email(self) -> None:
        self.repository.users_by_email[CURRENT_EMAIL]["email"] = None
        email_service = _fake_email_service()

        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self.client.post(
                "/api/auth/me/email-change/send-current",
                headers=self._headers(),
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"detail": "当前账号未绑定邮箱，暂不支持在线换绑"}
        )
        email_service.send_otp.assert_not_awaited()

    def test_ignores_stale_jwt_email_claim(self) -> None:
        email_service = _fake_email_service()

        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self.client.post(
                "/api/auth/me/email-change/send-current",
                headers=_bearer({"user_id": 7, "role": "user", "email": "old@example.com"}),
            )

        self.assertEqual(response.status_code, 200)
        email_service.send_otp.assert_awaited_once_with(
            CURRENT_EMAIL, purpose="email_change", deliver=True
        )

    def test_maps_cooldown_to_429(self) -> None:
        email_service = _fake_email_service()
        email_service.send_otp = AsyncMock(
            side_effect=OtpSendRateLimitedError("请求过于频繁，请 60 秒后再试")
        )

        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self.client.post(
                "/api/auth/me/email-change/send-current",
                headers=self._headers(),
            )

        self.assertEqual(response.status_code, 429)

    def test_maps_delivery_unavailable_to_503(self) -> None:
        email_service = _fake_email_service()
        email_service.send_otp = AsyncMock(
            side_effect=OtpDeliveryUnavailableError("邮件服务暂不可用，请稍后重试")
        )

        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self.client.post(
                "/api/auth/me/email-change/send-current",
                headers=self._headers(),
            )

        self.assertEqual(response.status_code, 503)


class SendEmailChangeNewOtpTests(_EmailChangeRouteTestBase):
    def test_delivers_to_normalized_new_email(self) -> None:
        email_service = _fake_email_service()

        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self.client.post(
                "/api/auth/me/email-change/send-new",
                headers=self._headers(),
                json={"new_email": "NewBox@Example.COM"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"detail": "验证码已发送至新邮箱"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        email_service.send_otp.assert_awaited_once_with(
            NEW_EMAIL, purpose="email_change", deliver=True
        )

    def test_requires_authentication(self) -> None:
        response = self.client.post(
            "/api/auth/me/email-change/send-new",
            json={"new_email": NEW_EMAIL},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.repository.events, [])

    def test_rejects_same_as_current_email(self) -> None:
        email_service = _fake_email_service()

        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self.client.post(
                "/api/auth/me/email-change/send-new",
                headers=self._headers(),
                json={"new_email": "Reader@Example.com"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "新邮箱不能与当前邮箱相同"})
        email_service.send_otp.assert_not_awaited()

    def test_rejects_account_without_email(self) -> None:
        self.repository.users_by_email[CURRENT_EMAIL]["email"] = None
        email_service = _fake_email_service()

        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self.client.post(
                "/api/auth/me/email-change/send-new",
                headers=self._headers(),
                json={"new_email": NEW_EMAIL},
            )

        self.assertEqual(response.status_code, 400)
        email_service.send_otp.assert_not_awaited()

    def test_validates_new_email_format(self) -> None:
        response = self.client.post(
            "/api/auth/me/email-change/send-new",
            headers=self._headers(),
            json={"new_email": "not-an-email"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.repository.events, [])

    def test_maps_cooldown_to_429(self) -> None:
        email_service = _fake_email_service()
        email_service.send_otp = AsyncMock(
            side_effect=OtpSendRateLimitedError("请求过于频繁，请 60 秒后再试")
        )

        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self.client.post(
                "/api/auth/me/email-change/send-new",
                headers=self._headers(),
                json={"new_email": NEW_EMAIL},
            )

        self.assertEqual(response.status_code, 429)


class ConfirmEmailChangeTests(_EmailChangeRouteTestBase):
    def _confirm(self, **overrides: Any) -> Any:
        payload = {
            "new_email": NEW_EMAIL,
            "current_code": CURRENT_CODE,
            "new_code": NEW_CODE,
        }
        payload.update(overrides)
        return self.client.post(
            "/api/auth/me/email-change/confirm",
            headers=self._headers(),
            json=payload,
        )

    def test_success_updates_email_and_returns_authoritative_projection(self) -> None:
        email_service = _dual_code_email_service()

        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self._confirm()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["email"], NEW_EMAIL)
        self.assertIs(payload["email_verified"], True)
        self.assertEqual(payload["user_id"], 7)
        self.assertNotIn("access_token", payload)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")
        # 双码均以 consume=False 预验，归属正确邮箱与独立用途
        verify_calls = email_service.verify_otp.await_args_list
        self.assertEqual(
            [(call.args[0], call.args[1]) for call in verify_calls],
            [(CURRENT_EMAIL, CURRENT_CODE), (NEW_EMAIL, NEW_CODE)],
        )
        for call in verify_calls:
            self.assertIs(call.kwargs["consume"], False)
            self.assertEqual(call.kwargs["purpose"], "email_change")
        self.assertEqual(
            self.repository.events,
            [
                ("get_user_by_email", NEW_EMAIL),
                ("update_user_email", 7, CURRENT_EMAIL, NEW_EMAIL),
            ],
        )
        # 仅在更新成功后消耗两枚验证码
        consume_calls = email_service.consume_otp.await_args_list
        self.assertEqual(
            [call.args[0] for call in consume_calls],
            [CURRENT_EMAIL, NEW_EMAIL],
        )
        for call in consume_calls:
            self.assertEqual(call.kwargs["purpose"], "email_change")
        serialized = response.content.decode()
        self.assertNotIn(CURRENT_CODE, serialized)
        self.assertNotIn(NEW_CODE, serialized)

    def test_requires_authentication(self) -> None:
        response = self.client.post(
            "/api/auth/me/email-change/confirm",
            json={
                "new_email": NEW_EMAIL,
                "current_code": CURRENT_CODE,
                "new_code": NEW_CODE,
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.repository.events, [])

    def test_rejects_invalid_current_code_without_mutation(self) -> None:
        email_service = _dual_code_email_service()

        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self._confirm(current_code="999999")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "验证码错误或已过期"})
        self.assertNotIn(
            "update_user_email", [event[0] for event in self.repository.events]
        )
        email_service.consume_otp.assert_not_awaited()
        # 新邮箱验证码不应被提前验证/消耗
        new_verify = [
            call for call in email_service.verify_otp.await_args_list
            if call.args[0] == NEW_EMAIL
        ]
        self.assertEqual(new_verify, [])

    def test_rejects_invalid_new_code_without_mutation(self) -> None:
        email_service = _dual_code_email_service()

        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self._confirm(new_code="999999")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "验证码错误或已过期"})
        self.assertNotIn(
            "update_user_email", [event[0] for event in self.repository.events]
        )
        email_service.consume_otp.assert_not_awaited()

    def test_rejects_same_email(self) -> None:
        email_service = _dual_code_email_service()

        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self._confirm(new_email="Reader@Example.com")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "新邮箱不能与当前邮箱相同"})
        email_service.verify_otp.assert_not_awaited()

    def test_rejects_email_owned_by_another_account_with_neutral_409(self) -> None:
        self.repository.users_by_email[NEW_EMAIL] = {
            "id": 9,
            "email": NEW_EMAIL,
            "role": "user",
            "hashed_password": hash_password("other-secret"),
        }
        email_service = _dual_code_email_service()

        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self._confirm()

        self.assertEqual(response.status_code, 409)
        # 中性文案：不确认该邮箱已被注册
        self.assertEqual(response.json(), {"detail": "换绑失败，请更换邮箱后重试"})
        self.assertNotIn(
            "update_user_email", [event[0] for event in self.repository.events]
        )
        email_service.consume_otp.assert_not_awaited()

    def test_verifies_codes_before_ownership_precheck(self) -> None:
        """无效验证码 + 已被占用邮箱：先报验证码错（400），不作归属探测 oracle。"""
        self.repository.users_by_email[NEW_EMAIL] = {
            "id": 9,
            "email": NEW_EMAIL,
            "role": "user",
            "hashed_password": hash_password("other-secret"),
        }
        email_service = _dual_code_email_service()

        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self._confirm(new_code="999999")

        self.assertEqual(response.status_code, 400)

    def test_snapshot_mismatch_fails_without_consuming_codes(self) -> None:
        self.repository.affected_rows = 0
        email_service = _dual_code_email_service()

        with patch.object(routes_auth, "_get_email_service", return_value=email_service):
            response = self._confirm()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "邮箱换绑失败，请稍后重试"})
        email_service.consume_otp.assert_not_awaited()
        # 验证码仍可重试：库内邮箱未被改写
        self.assertEqual(
            self.repository.users_by_email[CURRENT_EMAIL]["email"], CURRENT_EMAIL
        )

    def test_validates_code_format(self) -> None:
        response = self._confirm(current_code="abcde")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.repository.events, [])


if __name__ == "__main__":
    unittest.main()
