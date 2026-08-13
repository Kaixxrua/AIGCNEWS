from __future__ import annotations

import unittest
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_auth
from backend.app.api.dependencies import get_user_account_repository


class FakeUserAccountRepository:
    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        self.events = events
        self.users: dict[str, dict[str, Any]] = {}
        self.created_user_id = 42
        self.password_update_affected_rows = 1

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        self.events.append(("get_user_by_email", email))
        return self.users.get(email)

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
        return self.created_user_id

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
        return self.password_update_affected_rows


class FakeEmailService:
    def __init__(
        self,
        events: list[tuple[Any, ...]],
        *,
        verified: bool = True,
    ) -> None:
        self.events = events
        self.verified = verified

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


class AuthLifecycleRouteContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[tuple[Any, ...]] = []
        self.repository = FakeUserAccountRepository(self.events)
        app = FastAPI()
        app.include_router(routes_auth.router, prefix="/api")
        app.dependency_overrides[get_user_account_repository] = (
            lambda: self.repository
        )
        self.client = TestClient(app)

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        email_service: FakeEmailService,
        *,
        token_factory: Callable[[dict[str, Any]], str] | None = None,
    ):
        patches = [
            patch.object(
                routes_auth,
                "_get_email_service",
                return_value=email_service,
            )
        ]
        if token_factory is not None:
            patches.append(
                patch.object(routes_auth, "create_access_token", token_factory)
            )
        with patches[0]:
            if len(patches) == 1:
                return self.client.post(path, json=payload)
            with patches[1]:
                return self.client.post(path, json=payload)

    def assert_no_secret_leakage(
        self,
        response,
        *secrets: str,
    ) -> None:
        serialized = response.content.decode("utf-8").lower()
        serialized_headers = repr(dict(response.headers)).lower()
        for secret in secrets:
            self.assertNotIn(secret.lower(), serialized)
            self.assertNotIn(secret.lower(), serialized_headers)

    def test_openapi_freezes_auth_lifecycle_paths_and_request_schemas(self) -> None:
        document = self.client.get("/openapi.json").json()
        expected = {
            "/api/auth/send-email-otp": "SendEmailOtpRequest",
            "/api/auth/send-password-reset-otp": "SendEmailOtpRequest",
            "/api/auth/reset-password": "ResetPasswordRequest",
            "/api/auth/register": "RegisterRequest",
            "/api/auth/login": "LoginRequest",
            "/api/auth/me/password": "ChangePasswordRequest",
        }

        for path, schema in expected.items():
            operation = document["paths"][path]
            self.assertEqual(set(operation), {"post"})
            self.assertEqual(
                operation["post"]["requestBody"]["content"][
                    "application/json"
                ]["schema"],
                {"$ref": f"#/components/schemas/{schema}"},
            )

        schemas = document["components"]["schemas"]
        self.assertEqual(
            schemas["SendEmailOtpRequest"]["required"], ["email"]
        )
        self.assertEqual(
            schemas["RegisterRequest"]["required"],
            ["email", "email_code", "password"],
        )
        self.assertEqual(
            schemas["ResetPasswordRequest"]["required"],
            ["email", "email_code", "new_password"],
        )
        self.assertEqual(
            schemas["LoginRequest"]["required"], ["email", "password"]
        )
        self.assertEqual(
            schemas["ChangePasswordRequest"]["required"],
            ["current_password", "new_password"],
        )
        for schema, field in (
            ("SendEmailOtpRequest", "email"),
            ("RegisterRequest", "email"),
            ("ResetPasswordRequest", "email"),
            ("LoginRequest", "email"),
        ):
            self.assertEqual(
                schemas[schema]["properties"][field]["format"], "email"
            )

    def test_registration_preserves_normalized_domain_and_consumes_after_insert(self) -> None:
        service = FakeEmailService(self.events)
        payload = {
            "email": "Reader@EXAMPLE.COM",
            "email_code": "123456",
            "password": "plain-secret",
        }
        with patch.object(
            routes_auth, "hash_password", return_value="stored-password-hash"
        ):
            response = self._post(
                "/api/auth/register", payload, service
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"detail": "注册成功", "user_id": 42})
        self.assertEqual(
            self.events,
            [
                ("verify_otp", "Reader@example.com", "123456", False, "registration"),
                ("get_user_by_email", "Reader@example.com"),
                (
                    "create_user_with_email",
                    "Reader@example.com",
                    "stored-password-hash",
                    "user",
                    "",
                ),
                ("consume_otp", "Reader@example.com", "registration"),
            ],
        )
        self.assert_no_secret_leakage(
            response, "123456", "plain-secret", "stored-password-hash"
        )

    def test_duplicate_registration_returns_exact_conflict_without_consuming_otp(self) -> None:
        self.repository.users["Reader@example.com"] = {"id": 7}
        service = FakeEmailService(self.events)
        response = self._post(
            "/api/auth/register",
            {
                "email": "Reader@EXAMPLE.COM",
                "email_code": "123456",
                "password": "plain-secret",
            },
            service,
        )

        self.assertEqual(response.status_code, 409)
        # 反枚举：409 文案与 send_password_reset_otp 同口径，不透露邮箱是否已注册
        self.assertEqual(response.json(), {"detail": "注册失败，请检查邮箱验证码或稍后重试"})
        self.assertEqual(
            self.events,
            [
                ("verify_otp", "Reader@example.com", "123456", False, "registration"),
                ("get_user_by_email", "Reader@example.com"),
            ],
        )
        self.assert_no_secret_leakage(response, "123456", "plain-secret")

    def test_invalid_registration_otp_stops_before_account_lookup(self) -> None:
        service = FakeEmailService(self.events, verified=False)
        response = self._post(
            "/api/auth/register",
            {
                "email": "reader@example.com",
                "email_code": "123456",
                "password": "plain-secret",
            },
            service,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "验证码错误或已过期"})
        self.assertEqual(
            self.events,
            [
                ("verify_otp", "reader@example.com", "123456", False, "registration")
            ],
        )
        self.assert_no_secret_leakage(response, "123456", "plain-secret")

    def test_password_reset_send_is_anti_enumerating_and_controls_delivery(self) -> None:
        observed = []
        for user in (
            {"id": 7, "email": "reader@example.com"},
            None,
        ):
            self.events.clear()
            self.repository.users.clear()
            if user is not None:
                self.repository.users["reader@example.com"] = user
            service = FakeEmailService(self.events)
            response = self._post(
                "/api/auth/send-password-reset-otp",
                {"email": "Reader@EXAMPLE.COM"},
                service,
            )
            observed.append(
                (
                    response.status_code,
                    response.json(),
                    response.headers["cache-control"],
                    response.headers["pragma"],
                )
            )
            self.assertEqual(
                self.events,
                [
                    ("get_user_by_email", "reader@example.com"),
                    (
                        "send_otp",
                        "reader@example.com",
                        "password_reset",
                        user is not None,
                    ),
                ],
            )

        self.assertEqual(observed[0], observed[1])
        self.assertEqual(
            observed[0],
            (
                200,
                {"detail": "如果该邮箱已注册，验证码将发送至该邮箱"},
                "no-store",
                "no-cache",
            ),
        )

    def test_password_reset_verifies_then_updates_one_row_then_consumes(self) -> None:
        self.repository.users["reader@example.com"] = {
            "id": 7,
            "email": "reader@example.com",
        }
        service = FakeEmailService(self.events)
        with patch.object(
            routes_auth, "hash_password", return_value="replacement-hash"
        ):
            response = self._post(
                "/api/auth/reset-password",
                {
                    "email": "Reader@EXAMPLE.COM",
                    "email_code": "654321",
                    "new_password": "replacement-secret",
                },
                service,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"detail": "密码重置成功"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")
        self.assertEqual(
            self.events,
            [
                ("verify_otp", "reader@example.com", "654321", False, "password_reset"),
                ("get_user_by_email", "reader@example.com"),
                ("update_user_password", 7, "reader@example.com", "replacement-hash"),
                ("consume_otp", "reader@example.com", "password_reset"),
            ],
        )
        self.assert_no_secret_leakage(
            response, "654321", "replacement-secret", "replacement-hash"
        )

    def test_password_reset_requires_exactly_one_affected_row_without_consuming(self) -> None:
        for affected_rows in (0, 2):
            with self.subTest(affected_rows=affected_rows):
                self.events.clear()
                self.repository.users = {
                    "reader@example.com": {"id": 7, "email": "reader@example.com"}
                }
                self.repository.password_update_affected_rows = affected_rows
                service = FakeEmailService(self.events)
                with patch.object(
                    routes_auth, "hash_password", return_value="replacement-hash"
                ):
                    response = self._post(
                        "/api/auth/reset-password",
                        {
                            "email": "reader@example.com",
                            "email_code": "654321",
                            "new_password": "replacement-secret",
                        },
                        service,
                    )

                self.assertEqual(response.status_code, 500)
                self.assertEqual(
                    response.json(), {"detail": "密码重置失败，请稍后重试"}
                )
                self.assertEqual(
                    self.events[-1],
                    (
                        "update_user_password",
                        7,
                        "reader@example.com",
                        "replacement-hash",
                    ),
                )
                self.assertNotIn(
                    ("consume_otp", "reader@example.com", "password_reset"),
                    self.events,
                )
                self.assert_no_secret_leakage(
                    response, "654321", "replacement-secret", "replacement-hash"
                )

    def test_invalid_reset_code_and_missing_account_share_exact_error(self) -> None:
        outcomes = []
        for verified, user in ((False, {"id": 7}), (True, None)):
            self.events.clear()
            self.repository.users.clear()
            if user is not None:
                self.repository.users["reader@example.com"] = user
            service = FakeEmailService(self.events, verified=verified)
            response = self._post(
                "/api/auth/reset-password",
                {
                    "email": "Reader@EXAMPLE.COM",
                    "email_code": "654321",
                    "new_password": "replacement-secret",
                },
                service,
            )
            outcomes.append((response.status_code, response.json()))
            self.assertEqual(
                self.events[:2],
                [
                    ("verify_otp", "reader@example.com", "654321", False, "password_reset"),
                    ("get_user_by_email", "reader@example.com"),
                ],
            )
            self.assertEqual(len(self.events), 2)
            self.assert_no_secret_leakage(
                response, "654321", "replacement-secret"
            )

        self.assertEqual(
            outcomes,
            [
                (400, {"detail": "验证码错误或已过期"}),
                (400, {"detail": "验证码错误或已过期"}),
            ],
        )

    def test_login_normalization_invalid_credentials_and_jwt_claims(self) -> None:
        self.repository.users["Reader@example.com"] = {
            "id": 42,
            "email": "canonical@example.com",
            "role": "user",
            "hashed_password": "stored-password-hash",
        }
        captured_claims: list[dict[str, Any]] = []

        def token_factory(claims: dict[str, Any]) -> str:
            captured_claims.append(claims)
            return "signed.jwt.token"

        service = FakeEmailService(self.events)
        with patch.object(routes_auth, "verify_password", return_value=True) as verify:
            response = self._post(
                "/api/auth/login",
                {"email": "Reader@EXAMPLE.COM", "password": "plain-secret"},
                service,
                token_factory=token_factory,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "access_token": "signed.jwt.token",
                "token_type": "bearer",
                "role": "user",
                "password_change_required": False,
            },
        )
        self.assertEqual(self.events, [("get_user_by_email", "Reader@example.com")])
        verify.assert_called_once_with("plain-secret", "stored-password-hash")
        self.assertEqual(
            captured_claims,
            [
                {
                    "user_id": 42,
                    "role": "user",
                    "email": "canonical@example.com",
                    # 口令版本声明（AUTH-B）：记录缺 pwd_ver 键时按迁移 DEFAULT 1 签发
                    "pwd_ver": 1,
                }
            ],
        )
        self.assert_no_secret_leakage(
            response, "plain-secret", "stored-password-hash"
        )

        self.events.clear()
        self.repository.users.clear()
        missing = self._post(
            "/api/auth/login",
            {"email": "missing@example.com", "password": "plain-secret"},
            service,
        )
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json(), {"detail": "邮箱或密码错误"})
        self.assertEqual(
            self.events, [("get_user_by_email", "missing@example.com")]
        )
        self.assert_no_secret_leakage(missing, "plain-secret")

    def test_registration_otp_send_preserves_schema_normalization_and_exact_response(self) -> None:
        service = FakeEmailService(self.events)
        response = self._post(
            "/api/auth/send-email-otp",
            {"email": "Reader@EXAMPLE.COM"},
            service,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"detail": "验证码已发送"})
        self.assertEqual(
            self.events,
            [("send_otp", "Reader@example.com", "registration", True)],
        )


if __name__ == "__main__":
    unittest.main()
