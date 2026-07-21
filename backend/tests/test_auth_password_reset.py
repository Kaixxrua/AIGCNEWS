from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app.api import routes_auth
from backend.app.core.auth import verify_password
from backend.app.services.email_service import EmailService


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.expirations: dict[str, int] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: object, *, ex: int | None = None):
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex

    async def delete(self, *keys: str):
        for key in keys:
            self.values.pop(key, None)
            self.expirations.pop(key, None)

    async def incr(self, key: str) -> int:
        value = int(self.values.get(key, 0)) + 1
        self.values[key] = value
        return value

    async def expire(self, key: str, seconds: int):
        self.expirations[key] = seconds


class EmailResetOtpTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_rejects_when_redis_is_unavailable(self) -> None:
        service = EmailService(redis_client=None)
        with self.assertRaises(HTTPException) as context:
            await service.send_otp("user@example.com", deliver=False)
        self.assertEqual(context.exception.status_code, 503)

    async def test_registration_and_reset_codes_are_isolated(self) -> None:
        redis = FakeRedis()
        service = EmailService(redis_client=redis)

        await service.send_otp("User@Example.com", deliver=False)
        await service.send_otp(
            "User@Example.com", purpose="password_reset", deliver=False
        )

        self.assertIn("email:code:user@example.com", redis.values)
        self.assertIn("email:reset:code:user@example.com", redis.values)
        self.assertEqual(redis.expirations["email:code:user@example.com"], 300)
        self.assertEqual(redis.expirations["email:reset:lock:user@example.com"], 60)

    async def test_reset_code_is_single_use(self) -> None:
        redis = FakeRedis()
        service = EmailService(redis_client=redis)
        await service.send_otp(
            "user@example.com", purpose="password_reset", deliver=False
        )
        code = str(redis.values["email:reset:code:user@example.com"])

        self.assertTrue(
            await service.verify_otp(
                "user@example.com", code, purpose="password_reset"
            )
        )
        self.assertFalse(
            await service.verify_otp(
                "user@example.com", code, purpose="password_reset"
            )
        )

    async def test_reset_code_is_invalidated_after_five_failures(self) -> None:
        redis = FakeRedis()
        service = EmailService(redis_client=redis)
        await service.send_otp(
            "user@example.com", purpose="password_reset", deliver=False
        )

        for _ in range(5):
            self.assertFalse(
                await service.verify_otp(
                    "user@example.com", "000000", purpose="password_reset"
                )
            )

        self.assertNotIn("email:reset:code:user@example.com", redis.values)
        self.assertNotIn("email:reset:attempts:user@example.com", redis.values)


class PasswordResetRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.state.redis = FakeRedis()
        app.include_router(routes_auth.router, prefix="/api")
        self.client = TestClient(app)

    def test_send_code_response_does_not_enumerate_accounts(self) -> None:
        responses = []
        deliveries = []
        for user in ({"id": 7, "email": "user@example.com"}, None):
            repository = MagicMock()
            repository.get_user_by_email.return_value = user
            email_service = MagicMock()
            email_service.send_otp = AsyncMock()
            with (
                patch.object(routes_auth, "MySQLRepository", return_value=repository),
                patch.object(routes_auth, "_get_email_service", return_value=email_service),
            ):
                response = self.client.post(
                    "/api/auth/send-password-reset-otp",
                    json={"email": "user@example.com"},
                )
            responses.append((response.status_code, response.json()))
            deliveries.append(email_service.send_otp.await_args.kwargs["deliver"])
            self.assertEqual(response.headers["cache-control"], "no-store")

        self.assertEqual(responses[0], responses[1])
        self.assertEqual(deliveries, [True, False])

    def test_successful_reset_hashes_password_then_consumes_code(self) -> None:
        repository = MagicMock()
        repository.get_user_by_email.return_value = {
            "id": 7,
            "email": "user@example.com",
        }
        repository.update_user_password.return_value = 1
        email_service = MagicMock()
        email_service.verify_otp = AsyncMock(return_value=True)
        email_service.consume_otp = AsyncMock()

        with (
            patch.object(routes_auth, "MySQLRepository", return_value=repository),
            patch.object(routes_auth, "_get_email_service", return_value=email_service),
        ):
            response = self.client.post(
                "/api/auth/reset-password",
                json={
                    "email": "USER@example.com",
                    "email_code": "123456",
                    "new_password": "abcdef",
                },
            )

        self.assertEqual(response.status_code, 200)
        kwargs = repository.update_user_password.call_args.kwargs
        self.assertEqual(kwargs["user_id"], 7)
        self.assertEqual(kwargs["email"], "user@example.com")
        self.assertNotEqual(kwargs["hashed_password"], "abcdef")
        self.assertTrue(verify_password("abcdef", kwargs["hashed_password"]))
        email_service.consume_otp.assert_awaited_once_with(
            "user@example.com", purpose="password_reset"
        )

    def test_invalid_code_and_missing_account_share_response(self) -> None:
        results = []
        for verified, user in ((False, {"id": 7}), (True, None)):
            repository = MagicMock()
            repository.get_user_by_email.return_value = user
            email_service = MagicMock()
            email_service.verify_otp = AsyncMock(return_value=verified)
            with (
                patch.object(routes_auth, "MySQLRepository", return_value=repository),
                patch.object(routes_auth, "_get_email_service", return_value=email_service),
            ):
                response = self.client.post(
                    "/api/auth/reset-password",
                    json={
                        "email": "user@example.com",
                        "email_code": "123456",
                        "new_password": "abcdef",
                    },
                )
            results.append((response.status_code, response.json()))

        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0], 400)

    def test_zero_row_update_does_not_consume_code(self) -> None:
        repository = MagicMock()
        repository.get_user_by_email.return_value = {
            "id": 7,
            "email": "user@example.com",
        }
        repository.update_user_password.return_value = 0
        email_service = MagicMock()
        email_service.verify_otp = AsyncMock(return_value=True)
        email_service.consume_otp = AsyncMock()

        with (
            patch.object(routes_auth, "MySQLRepository", return_value=repository),
            patch.object(routes_auth, "_get_email_service", return_value=email_service),
        ):
            response = self.client.post(
                "/api/auth/reset-password",
                json={
                    "email": "user@example.com",
                    "email_code": "123456",
                    "new_password": "abcdef",
                },
            )

        self.assertEqual(response.status_code, 500)
        email_service.consume_otp.assert_not_awaited()

    def test_reset_request_validation(self) -> None:
        common = {"email": "user@example.com", "email_code": "123456"}
        short = self.client.post(
            "/api/auth/reset-password",
            json={**common, "new_password": "12345"},
        )
        long_utf8 = self.client.post(
            "/api/auth/reset-password",
            json={**common, "new_password": "界" * 25},
        )
        malformed_code = self.client.post(
            "/api/auth/reset-password",
            json={**common, "email_code": "12345x", "new_password": "abcdef"},
        )

        self.assertEqual(short.status_code, 422)
        self.assertEqual(long_utf8.status_code, 422)
        self.assertEqual(malformed_code.status_code, 422)


if __name__ == "__main__":
    unittest.main()
