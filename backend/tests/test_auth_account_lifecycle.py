from __future__ import annotations

import dataclasses
import unittest
from collections.abc import Mapping
from typing import Any

from backend.app.services.auth.account_lifecycle import (
    AccountAlreadyExists,
    AccountLifecycle,
    InvalidCredentials,
    InvalidOtp,
    LoginResult,
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

    def get_user_by_email(self, email: str) -> Mapping[str, Any] | None:
        self.events.append(("get_user_by_email", email))
        return self.users.get(email)

    def create_user_with_email(
        self,
        email: str,
        hashed_password: str,
        role: str = "user",
        username: str = "",
        *,
        promote_if_first: bool = False,
    ) -> int:
        self.events.append(
            (
                "create_user_with_email",
                email,
                hashed_password,
                role,
                username,
                promote_if_first,
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

        def verify_password(password: str, password_hash: str) -> bool:
            self.events.append(("verify_password", password, password_hash))
            return True

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
                    "",
                    True,
                ),
                ("consume_otp", "Reader@example.com", "registration"),
            ],
        )
        self.assert_no_plaintext_secrets(result, "123456", "plain-secret", "stored-password-hash")

    async def test_register_requests_first_user_promotion_with_user_fallback(self) -> None:
        await self.lifecycle.register(
            email="reader@example.com",
            email_code="123456",
            password="plain-secret",
        )

        create_events = [
            event for event in self.events if event[0] == "create_user_with_email"
        ]
        self.assertEqual(len(create_events), 1)
        _, _, _, fallback_role, _, promote_if_first = create_events[0]
        # 回退角色恒为 user；是否提权 admin 由仓储按用户表是否为空决定
        self.assertEqual(fallback_role, "user")
        self.assertIs(promote_if_first, True)

    async def test_registration_failures_stop_before_hash_and_consumption(self) -> None:
        self.otp.verified = False
        with self.assertRaises(InvalidOtp):
            await self.lifecycle.register(
                email="reader@example.com",
                email_code="123456",
                password="plain-secret",
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
                    },
                ),
            ],
        )
        self.assert_no_plaintext_secrets(result, "plain-secret", "stored-password-hash")

    async def test_login_missing_account_does_not_verify_or_issue(self) -> None:
        with self.assertRaises(InvalidCredentials):
            await self.lifecycle.login(
                email="missing@example.com", password="plain-secret"
            )
        self.assertEqual(
            self.events,
            [("get_user_by_email", "missing@example.com")],
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

    def assert_no_plaintext_secrets(self, result: object, *secrets: str) -> None:
        self.assertTrue(dataclasses.is_dataclass(result))
        serialized = repr(dataclasses.asdict(result)).lower()
        for secret in secrets:
            self.assertNotIn(secret.lower(), serialized)


if __name__ == "__main__":
    unittest.main()
