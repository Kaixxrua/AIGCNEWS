from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from backend.app.repositories.postgres_oauth_identity_repository import (
    PostgresOAuthIdentityRepository,
)


class FakeDatabase:
    def __init__(self, cursor: MagicMock) -> None:
        self.cursor = cursor
        self.connection = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = cursor
        self.connection.cursor.return_value = context
        self.transactions = 0

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield self.connection


def test_resolve_first_login_uses_one_transaction_and_sorted_advisory_locks() -> None:
    cursor = MagicMock()
    cursor.fetchone.side_effect = [None, {"id": 7, "email": "a@example.com", "email_verified": True, "role": "user", "disabled": False}, {"id": 12}]
    database = FakeDatabase(cursor)
    repository = PostgresOAuthIdentityRepository(database)

    with patch(
        "backend.app.repositories.postgres_oauth_identity_repository.hash_password",
        return_value="random-unusable-hash",
    ):
        result = repository.resolve_first_login(
            provider="github",
            provider_subject="subject-1",
            display_email="A@EXAMPLE.COM",
            email_verified=True,
        )

    assert result.status == "authenticated"
    assert database.transactions == 1
    lock_calls = [
        call.args[1][0]
        for call in cursor.execute.call_args_list
        if "pg_advisory_xact_lock" in call.args[0]
    ]
    assert lock_calls == sorted(lock_calls)
    sql = "\n".join(call.args[0] for call in cursor.execute.call_args_list)
    assert "FOR UPDATE OF i, u" in sql
    assert "FOR UPDATE" in sql
    assert "ON CONFLICT (provider, provider_subject) DO NOTHING" in sql


def test_oauth_only_creation_never_marks_null_email_verified() -> None:
    cursor = MagicMock()
    cursor.fetchone.side_effect = [{"id": 9, "email": None, "role": "user"}, {"id": 12}]
    database = FakeDatabase(cursor)
    repository = PostgresOAuthIdentityRepository(database)

    with patch(
        "backend.app.repositories.postgres_oauth_identity_repository.hash_password",
        return_value="random-unusable-hash",
    ):
        repository.create_oauth_only_user(
            provider="wechat",
            provider_subject="openid-1",
            display_email=None,
            email_verified=True,
        )

    insert_params = cursor.execute.call_args_list[0].args[1]
    assert insert_params[-1] is False
    identity_params = cursor.execute.call_args_list[1].args[1]
    assert identity_params[-1] is False
