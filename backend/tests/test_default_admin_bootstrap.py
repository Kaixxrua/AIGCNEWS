from __future__ import annotations

import unittest
from typing import Any

from backend.app.services.auth.default_admin_bootstrap import (
    ensure_default_admin,
    password_change_required_for_email,
    uses_configured_default_credentials,
)


class FakeRepository:
    def __init__(self, *, user_count: int = 0) -> None:
        self.user_count = user_count
        self.users: dict[str, dict[str, Any]] = {}
        self.create_calls: list[tuple[Any, ...]] = []
        self.create_error: Exception | None = None

    def get_user_count(self) -> int:
        return self.user_count

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        return self.users.get(email)

    def create_user_with_email(
        self,
        email: str,
        hashed_password: str,
        role: str = "user",
        username: str = "",
    ) -> int:
        if self.create_error is not None:
            raise self.create_error
        self.create_calls.append((email, hashed_password, role, username))
        self.users[email] = {
            "id": 1,
            "email": email,
            "hashed_password": hashed_password,
            "role": role,
        }
        return 1


def fake_hash(password: str) -> str:
    return f"hashed:{password}"


def fake_verify(password: str, hashed: str) -> bool:
    return hashed == f"hashed:{password}"


class EnsureDefaultAdminTests(unittest.TestCase):
    def test_empty_users_table_seeds_admin_with_normalized_email(self) -> None:
        repository = FakeRepository(user_count=0)

        seeded = ensure_default_admin(
            repository=repository,
            email="Admin@AIGCNews.INTERNAL",
            password="plain-secret",
            hash_password=fake_hash,
        )

        self.assertTrue(seeded)
        self.assertEqual(
            repository.create_calls,
            [("admin@aigcnews.internal", "hashed:plain-secret", "admin", "admin")],
        )

    def test_non_empty_users_table_is_no_op(self) -> None:
        repository = FakeRepository(user_count=3)

        seeded = ensure_default_admin(
            repository=repository,
            email="admin@aigcnews.internal",
            password="plain-secret",
            hash_password=fake_hash,
        )

        self.assertFalse(seeded)
        self.assertEqual(repository.create_calls, [])

    def test_blank_email_or_password_disables_seed(self) -> None:
        for email, password in (("", "plain-secret"), ("admin@aigcnews.internal", ""), ("  ", "plain-secret")):
            with self.subTest(email=email, password=password):
                repository = FakeRepository(user_count=0)

                seeded = ensure_default_admin(
                    repository=repository,
                    email=email,
                    password=password,
                    hash_password=fake_hash,
                )

                self.assertFalse(seeded)
                self.assertEqual(repository.create_calls, [])

    def test_unique_violation_is_tolerated_as_concurrent_seed(self) -> None:
        repository = FakeRepository(user_count=0)
        repository.create_error = Exception(
            'duplicate key value violates unique constraint "users_email_key"'
        )

        seeded = ensure_default_admin(
            repository=repository,
            email="admin@aigcnews.internal",
            password="plain-secret",
            hash_password=fake_hash,
        )

        self.assertFalse(seeded)

    def test_unexpected_create_error_propagates(self) -> None:
        repository = FakeRepository(user_count=0)
        repository.create_error = RuntimeError("connection lost")

        with self.assertRaises(RuntimeError):
            ensure_default_admin(
                repository=repository,
                email="admin@aigcnews.internal",
                password="plain-secret",
                hash_password=fake_hash,
            )


class DefaultCredentialPredicatesTests(unittest.TestCase):
    def test_uses_configured_default_credentials_matches_case_insensitive_email(self) -> None:
        self.assertTrue(
            uses_configured_default_credentials(
                email="Admin@AIGCNEWS.INTERNAL",
                password="admin123456",
                configured_email="admin@aigcnews.internal",
                configured_password="admin123456",
            )
        )

    def test_uses_configured_default_credentials_rejects_mismatches_and_blanks(self) -> None:
        base = {
            "email": "admin@aigcnews.internal",
            "password": "admin123456",
            "configured_email": "admin@aigcnews.internal",
            "configured_password": "admin123456",
        }
        for override in (
            {"email": "other@example.com"},
            {"password": "other-secret"},
            {"email": ""},
            {"password": ""},
            {"configured_password": ""},
        ):
            with self.subTest(override=override):
                self.assertFalse(
                    uses_configured_default_credentials(**(base | override))
                )

    def test_password_change_required_short_circuits_before_repository(self) -> None:
        repository = FakeRepository(user_count=1)

        result = password_change_required_for_email(
            repository=repository,
            email="reader@example.com",
            configured_email="admin@aigcnews.internal",
            configured_password="admin123456",
            verify_password=fake_verify,
        )

        self.assertFalse(result)

    def test_password_change_required_reflects_stored_hash(self) -> None:
        repository = FakeRepository(user_count=1)
        repository.users["admin@aigcnews.internal"] = {
            "id": 1,
            "email": "admin@aigcnews.internal",
            "hashed_password": "hashed:admin123456",
        }

        still_default = password_change_required_for_email(
            repository=repository,
            email="admin@aigcnews.internal",
            configured_email="admin@aigcnews.internal",
            configured_password="admin123456",
            verify_password=fake_verify,
        )
        self.assertTrue(still_default)

        repository.users["admin@aigcnews.internal"]["hashed_password"] = "hashed:rotated"
        rotated = password_change_required_for_email(
            repository=repository,
            email="admin@aigcnews.internal",
            configured_email="admin@aigcnews.internal",
            configured_password="admin123456",
            verify_password=fake_verify,
        )
        self.assertFalse(rotated)

    def test_password_change_required_handles_missing_user_and_blank_config(self) -> None:
        repository = FakeRepository(user_count=0)

        missing_user = password_change_required_for_email(
            repository=repository,
            email="admin@aigcnews.internal",
            configured_email="admin@aigcnews.internal",
            configured_password="admin123456",
            verify_password=fake_verify,
        )
        blank_config = password_change_required_for_email(
            repository=repository,
            email="admin@aigcnews.internal",
            configured_email="admin@aigcnews.internal",
            configured_password="",
            verify_password=fake_verify,
        )

        self.assertFalse(missing_user)
        self.assertFalse(blank_config)


if __name__ == "__main__":
    unittest.main()
