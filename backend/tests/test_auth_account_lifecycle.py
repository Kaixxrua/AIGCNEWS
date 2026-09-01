from __future__ import annotations

import dataclasses
import unittest
from collections.abc import Mapping
from typing import Any

from backend.app.services.auth.account_lifecycle import (
    AccountAlreadyExists,
    AccountDisabled,
    AccountLifecycle,
    InvalidCredentials,
    InvalidOtp,
    LoginResult,
    PasswordChangeFailed,
    PasswordChangeResult,
    PasswordResetFailed,
    PasswordResetResult,
    RegistrationResult,
    ResetOtpRequestResult,
)


class FakeRepository:
    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        self.events = events
        self.users: dict[str, Mapping[str, Any]] = {}
        self.affected_rows = 1

    def get_user_by_id(self, user_id: int) -> Mapping[str, Any] | None:
        self.events.append(("get_user_by_id", user_id))
        for user in self.users.values():
            if int(user.get("id", 0)) == int(user_id):
                return user
        return None

    def get_user_by_email(self, email: str) -> Mapping[str, Any] | None:
        self.events.append(("get_user_by_email", email))
        return self.users.get(email)

    def update_user_username(self, *, user_id: int, username: str) -> int:
        self.events.append(("update_user_username", user_id, username))
        return self.affected_rows

    def create_user_with_email(
        self,
        email: str,
        hashed_password: str,
        role: str = "user",
        username: str = "",
    ) -> int:
        self.events.append(
            (
                "create_user_with_email",
                email,
                hashed_password,
                role,
                username,
            )
        )
        return 42

    def update_user_password(
        self,
        *,
        user_id: int,
        email: str,
        hashed_password: str,
    ) -> int:
        self.events.append(
            ("update_user_password", user_id, email, hashed_password)
        )
        if self.affected_rows == 1:
            for user in self.users.values():
                if int(user.get("id", 0)) == int(user_id):
                    if isinstance(user, dict):
                        user["pwd_ver"] = int(user.get("pwd_ver") or 1) + 1
                    break
        return self.affected_rows


class FakeOtpService:
    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        self.events = events
        self.verified = True

    async def send_otp(
        self,
        email: str,
        *,
        purpose: str = "registration",
        deliver: bool = True,
    ) -> None:
        self.events.append(("send_otp", email, purpose, deliver))

    async def verify_otp(
        self,
        email: str,
        code: str,
        consume: bool = True,
        *,
        purpose: str = "registration",
    ) -> bool:
        self.events.append(("verify_otp", email, code, consume, purpose))
        return self.verified

    async def consume_otp(
        self,
        email: str,
        *,
        purpose: str = "registration",
    ) -> None:
        self.events.append(("consume_otp", email, purpose))


class AccountLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.events: list[tuple[Any, ...]] = []
        self.repository = FakeRepository(self.events)
        self.otp = FakeOtpService(self.events)

        def hash_password(password: str) -> str:
            self.events.append(("hash_password", password))
            return "stored-password-hash"

        self.verify_password_result = True

        def verify_password(password: str, password_hash: str) -> bool:
            self.events.append(("verify_password", password, password_hash))
            return self.verify_password_result

        def issue_token(claims: dict[str, Any]) -> str:
            self.events.append(("issue_token", claims))
            return "signed.jwt.token"

        self.lifecycle = AccountLifecycle(
            repository=self.repository,
            otp=self.otp,
            hash_password=hash_password,
            verify_password=verify_password,
            issue_token=issue_token,
        )

    async def test_registration_preserves_order_and_consumes_after_insert(self) -> None:
        result = await self.lifecycle.register(
            email="Reader@EXAMPLE.COM",
            email_code="123456",
            password="plain-secret",
            username="  读者甲  ",
        )

        self.assertEqual(result, RegistrationResult(user_id=42))
        self.assertEqual(
            self.events,
            [
                ("verify_otp", "Reader@example.com", "123456", False, "registration"),
                ("get_user_by_email", "Reader@example.com"),
                ("hash_password", "plain-secret"),
                (
                    "create_user_with_email",
                    "Reader@example.com",
                    "stored-password-hash",
                    "user",
                    "读者甲",
                ),
                ("consume_otp", "Reader@example.com", "registration"),
            ],
        )
        self.assert_no_plaintext_secrets(result, "123456", "plain-secret", "stored-password-hash")

    async def test_registration_failures_stop_before_hash_and_consumption(self) -> None:
        self.otp.verified = False
        with self.assertRaises(InvalidOtp):
            await self.lifecycle.register(
                email="reader@example.com",
                email_code="123456",
                password="plain-secret",
                username="读者甲",
            )
        self.assertEqual(
            self.events,
            [("verify_otp", "reader@example.com", "123456", False, "registration")],
        )

        self.events.clear()
        self.otp.verified = True
        self.repository.users["reader@example.com"] = {"id": 7}
        with self.assertRaises(AccountAlreadyExists):
            await self.lifecycle.register(
                email="reader@example.com",
                email_code="123456",
                password="plain-secret",
                username="读者甲",
            )
        self.assertEqual(
            self.events,
            [
                ("verify_otp", "reader@example.com", "123456", False, "registration"),
                ("get_user_by_email", "reader@example.com"),
            ],
        )

    async def test_login_preserves_lookup_verify_claims_and_issue_order(self) -> None:
        self.repository.users["Reader@example.com"] = {
            "id": 42,
            "email": "canonical@example.com",
            "role": "user",
            "hashed_password": "stored-password-hash",
            "pwd_ver": 3,
        }

        result = await self.lifecycle.login(
            email="Reader@EXAMPLE.COM", password="plain-secret"
        )

        self.assertEqual(
            result,
            LoginResult(
                access_token="signed.jwt.token",
                token_type="bearer",
                role="user",
            ),
        )
        self.assertEqual(
            self.events,
            [
                ("get_user_by_email", "Reader@example.com"),
                ("verify_password", "plain-secret", "stored-password-hash"),
                (
                    "issue_token",
                    {
                        "user_id": 42,
                        "role": "user",
                        "email": "canonical@example.com",
                        "pwd_ver": 3,
                    },
                ),
            ],
        )
        self.assert_no_plaintext_secrets(result, "plain-secret", "stored-password-hash")

    async def test_login_defaults_pwd_ver_claim_for_legacy_records(self) -> None:
        # 仓储记录缺 pwd_ver 键（未升级替身/历史仓储）时声明按 1 签发，
        # 与迁移 0041 的 DEFAULT 1 同口径
        self.repository.users["reader@example.com"] = {
            "id": 7,
            "email": "reader@example.com",
            "role": "user",
            "hashed_password": "stored-password-hash",
        }

        await self.lifecycle.login(email="reader@example.com", password="plain-secret")

        claims = self.events[-1][1]
        self.assertEqual(claims["pwd_ver"], 1)

    async def test_login_missing_account_does_not_verify_or_issue(self) -> None:
        with self.assertRaises(InvalidCredentials):
            await self.lifecycle.login(
                email="missing@example.com", password="plain-secret"
            )
        self.assertEqual(
            self.events,
            [("get_user_by_email", "missing@example.com")],
        )

    async def test_oauth_only_account_never_verifies_password_or_issues(self) -> None:
        self.repository.users["reader@example.com"] = {
            "id": 42,
            "email": "reader@example.com",
            "role": "user",
            "hashed_password": "unusable-password-hash",
            "password_login_enabled": False,
        }

        with self.assertRaises(InvalidCredentials):
            await self.lifecycle.login(
                email="reader@example.com", password="plain-secret"
            )

        self.assertEqual(
            self.events,
            [("get_user_by_email", "reader@example.com")],
        )

    async def test_login_disabled_account_verifies_password_but_never_issues(self) -> None:
        # 禁用判定必须在密码核验之后：不向密码错误方泄露禁用状态，
        # 但密码正确也绝不签发令牌（渗透实测：禁用账号原可登录拿 JWT）
        self.repository.users["reader@example.com"] = {
            "id": 42,
            "email": "reader@example.com",
            "role": "user",
            "hashed_password": "stored-password-hash",
            "disabled": True,
        }

        with self.assertRaises(AccountDisabled):
            await self.lifecycle.login(
                email="reader@example.com", password="plain-secret"
            )

        self.assertEqual(
            self.events,
            [
                ("get_user_by_email", "reader@example.com"),
                ("verify_password", "plain-secret", "stored-password-hash"),
            ],
        )

        self.events.clear()
        self.verify_password_result = False
        with self.assertRaises(InvalidCredentials):
            await self.lifecycle.login(
                email="reader@example.com", password="wrong-secret"
            )

    async def test_reset_otp_request_is_anti_enumerating_and_controls_delivery(self) -> None:
        results = []
        for user in ({"id": 7}, None):
            self.events.clear()
            self.repository.users.clear()
            if user is not None:
                self.repository.users["reader@example.com"] = user

            result = await self.lifecycle.request_password_reset_otp(
                email="Reader@EXAMPLE.COM"
            )
            results.append(result)
            self.assertEqual(
                self.events,
                [
                    ("get_user_by_email", "reader@example.com"),
                    ("send_otp", "reader@example.com", "password_reset", user is not None),
                ],
            )

        self.assertEqual(results, [ResetOtpRequestResult(), ResetOtpRequestResult()])

    async def test_password_reset_preserves_verify_lookup_hash_update_consume_order(self) -> None:
        self.repository.users["reader@example.com"] = {"id": 7}

        result = await self.lifecycle.reset_password(
            email="Reader@EXAMPLE.COM",
            email_code="654321",
            new_password="replacement-secret",
        )

        self.assertEqual(result, PasswordResetResult())
        self.assertEqual(
            self.events,
            [
                ("verify_otp", "reader@example.com", "654321", False, "password_reset"),
                ("get_user_by_email", "reader@example.com"),
                ("hash_password", "replacement-secret"),
                ("update_user_password", 7, "reader@example.com", "stored-password-hash"),
                ("consume_otp", "reader@example.com", "password_reset"),
            ],
        )
        self.assert_no_plaintext_secrets(
            result, "654321", "replacement-secret", "stored-password-hash"
        )

    async def test_password_reset_always_looks_up_account_after_verification(self) -> None:
        for verified, user in ((False, {"id": 7}), (True, None)):
            with self.subTest(verified=verified, user=user):
                self.events.clear()
                self.otp.verified = verified
                self.repository.users.clear()
                if user is not None:
                    self.repository.users["reader@example.com"] = user

                with self.assertRaises(InvalidOtp):
                    await self.lifecycle.reset_password(
                        email="Reader@EXAMPLE.COM",
                        email_code="654321",
                        new_password="replacement-secret",
                    )
                self.assertEqual(
                    self.events,
                    [
                        ("verify_otp", "reader@example.com", "654321", False, "password_reset"),
                        ("get_user_by_email", "reader@example.com"),
                    ],
                )

    async def test_password_reset_requires_exactly_one_updated_row(self) -> None:
        self.repository.users["reader@example.com"] = {"id": 7}
        for affected_rows in (0, 2):
            with self.subTest(affected_rows=affected_rows):
                self.events.clear()
                self.repository.affected_rows = affected_rows
                with self.assertRaises(PasswordResetFailed):
                    await self.lifecycle.reset_password(
                        email="reader@example.com",
                        email_code="654321",
                        new_password="replacement-secret",
                    )
                self.assertEqual(self.events[-1][0], "update_user_password")
                self.assertNotIn(
                    ("consume_otp", "reader@example.com", "password_reset"),
                    self.events,
                )

    async def test_request_change_password_otp_delivers_to_existing_account(self) -> None:
        self.repository.users["Reader@example.com"] = {
            "id": 7,
            "email": "Reader@example.com",
        }

        result = await self.lifecycle.request_change_password_otp(user_id=7)

        self.assertEqual(result, ResetOtpRequestResult())
        self.assertEqual(
            self.events,
            [
                ("get_user_by_id", 7),
                ("send_otp", "Reader@example.com", "password_change", True),
            ],
        )

    async def test_request_change_password_otp_rejects_missing_account(self) -> None:
        with self.assertRaises(InvalidCredentials):
            await self.lifecycle.request_change_password_otp(user_id=404)

        self.assertEqual(self.events, [("get_user_by_id", 404)])

    async def test_change_password_verifies_otp_then_rotates_token(self) -> None:
        self.repository.users["Reader@example.com"] = {
            "id": 7,
            "email": "reader@example.com",
            "role": "user",
            "pwd_ver": 3,
            "hashed_password": "old-password-hash",
        }

        result = await self.lifecycle.change_password(
            user_id=7,
            email_code="654321",
            new_password="replacement-secret",
        )

        self.assertEqual(result, PasswordChangeResult(access_token="signed.jwt.token"))
        self.assertEqual(
            self.events,
            [
                ("get_user_by_id", 7),
                ("verify_otp", "reader@example.com", "654321", False, "password_change"),
                ("hash_password", "replacement-secret"),
                ("update_user_password", 7, "reader@example.com", "stored-password-hash"),
                ("get_user_by_id", 7),
                ("issue_token", {
                    "user_id": 7,
                    "role": "user",
                    "email": "reader@example.com",
                    "pwd_ver": 4,
                }),
                ("consume_otp", "reader@example.com", "password_change"),
            ],
        )
        self.assert_no_plaintext_secrets(
            result, "replacement-secret", "stored-password-hash"
        )

    async def test_change_password_rejects_invalid_otp_without_update(self) -> None:
        self.repository.users["reader@example.com"] = {
            "id": 7,
            "email": "reader@example.com",
            "role": "user",
            "pwd_ver": 1,
        }
        self.otp.verified = False

        with self.assertRaises(InvalidOtp):
            await self.lifecycle.change_password(
                user_id=7,
                email_code="000000",
                new_password="replacement-secret",
            )
        self.assertEqual(
            self.events,
            [
                ("get_user_by_id", 7),
                ("verify_otp", "reader@example.com", "000000", False, "password_change"),
            ],
        )

    async def test_change_password_missing_account_rejects_before_otp(self) -> None:
        with self.assertRaises(InvalidCredentials):
            await self.lifecycle.change_password(
                user_id=404,
                email_code="654321",
                new_password="replacement-secret",
            )
        self.assertEqual(self.events, [("get_user_by_id", 404)])

    async def test_change_password_requires_exactly_one_updated_row(self) -> None:
        self.repository.users["reader@example.com"] = {
            "id": 7,
            "email": "reader@example.com",
            "role": "user",
            "pwd_ver": 1,
        }
        self.repository.affected_rows = 0

        with self.assertRaises(PasswordChangeFailed):
            await self.lifecycle.change_password(
                user_id=7,
                email_code="654321",
                new_password="replacement-secret",
            )
        self.assertEqual(self.events[-1][0], "update_user_password")
        self.assertNotIn(
            ("consume_otp", "reader@example.com", "password_change"),
            self.events,
        )

    def assert_no_plaintext_secrets(self, result: object, *secrets: str) -> None:
        self.assertTrue(dataclasses.is_dataclass(result))
        serialized = repr(dataclasses.asdict(result)).lower()
        for secret in secrets:
            self.assertNotIn(secret.lower(), serialized)


if __name__ == "__main__":
    unittest.main()
