from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from backend.app.repositories.postgres_oauth_identity_repository import (
    PostgresOAuthIdentityRepository,
    _resolve_oauth_username,
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


def test_resolve_oauth_username_fallback_chain() -> None:
    # provider 用户名优先（裁剪空白）
    assert _resolve_oauth_username("  octocat  ", "a@example.com") == "octocat"
    # 无用户名回退 provider 邮箱
    assert _resolve_oauth_username("", "a@example.com") == "a@example.com"
    assert _resolve_oauth_username("   ", "a@example.com") == "a@example.com"
    # 两者皆空（微信无邮箱场景）写空串
    assert _resolve_oauth_username("", None) == ""
    assert _resolve_oauth_username("  ", "  ") == ""
    # provider 数据不可信：超长按 VARCHAR(64) 截断而非报错回滚
    assert _resolve_oauth_username("x" * 80, None) == "x" * 64


def _user_insert_params(cursor: MagicMock) -> tuple:
    for call in cursor.execute.call_args_list:
        if "INSERT INTO users" in call.args[0]:
            return call.args[1]
    raise AssertionError("no INSERT INTO users call recorded")


def test_resolve_first_login_insert_carries_resolved_username() -> None:
    cursor = MagicMock()
    # 身份未命中 → 有 canonical email 时查 owner 未命中 → INSERT users → INSERT identity
    cursor.fetchone.side_effect = [None, None, {"id": 7, "email": "a@example.com"}, {"id": 12}]
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
            username="octocat",
        )

    assert result.status == "authenticated"
    params = _user_insert_params(cursor)
    # 参数位 1 是 username 列：provider 用户名优先于邮箱
    assert params[1] == "octocat"


def test_resolve_first_login_insert_falls_back_to_email_then_empty() -> None:
    for username, display_email, expected in (
        ("", "a@example.com", "a@example.com"),
        ("", None, ""),
    ):
        cursor = MagicMock()
        # 无 canonical email（email_verified=False）时不查 owner：身份未命中 → INSERT → identity
        cursor.fetchone.side_effect = [None, {"id": 7, "email": None}, {"id": 12}]
        database = FakeDatabase(cursor)
        repository = PostgresOAuthIdentityRepository(database)

        with patch(
            "backend.app.repositories.postgres_oauth_identity_repository.hash_password",
            return_value="random-unusable-hash",
        ):
            repository.resolve_first_login(
                provider="wechat",
                provider_subject="openid-1",
                display_email=display_email,
                email_verified=False,
                username=username,
            )

        params = _user_insert_params(cursor)
        assert params[1] == expected


def test_create_oauth_only_user_insert_carries_resolved_username() -> None:
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
            email_verified=False,
            username="  微信用户  ",
        )

    params = _user_insert_params(cursor)
    assert params[1] == "微信用户"


def _lock_keys(cursor: MagicMock) -> list[str]:
    return [
        call.args[1][0]
        for call in cursor.execute.call_args_list
        if "pg_advisory_xact_lock" in call.args[0]
    ]


def test_bind_identity_inserts_under_subject_advisory_lock() -> None:
    cursor = MagicMock()
    # 身份未命中 → INSERT ... RETURNING id
    cursor.fetchone.side_effect = [None, {"id": 12}]
    database = FakeDatabase(cursor)
    repository = PostgresOAuthIdentityRepository(database)

    result = repository.bind_identity(
        user_id=7,
        provider="github",
        provider_subject="subject-1",
        display_email="a@example.com",
        email_verified=True,
    )

    assert result.status == "bound"
    assert database.transactions == 1
    # 与 resolve_first_login 共用同一 lock 键：绑定与首次登录建号互斥
    assert _lock_keys(cursor) == ["oauth:subject:github:subject-1"]
    sql = "\n".join(call.args[0] for call in cursor.execute.call_args_list)
    assert "FOR UPDATE" in sql
    assert "ON CONFLICT (provider, provider_subject) DO NOTHING" in sql
    insert_call = [
        call for call in cursor.execute.call_args_list
        if "INSERT INTO user_oauth_identities" in call.args[0]
    ][0]
    assert insert_call.args[1] == (7, "github", "subject-1", "a@example.com", True)


def test_bind_identity_same_owner_is_idempotent() -> None:
    cursor = MagicMock()
    cursor.fetchone.side_effect = [{"user_id": 7}]
    database = FakeDatabase(cursor)
    repository = PostgresOAuthIdentityRepository(database)

    result = repository.bind_identity(
        user_id=7, provider="github", provider_subject="subject-1"
    )

    assert result.status == "already_bound"
    sql = "\n".join(call.args[0] for call in cursor.execute.call_args_list)
    assert "INSERT INTO user_oauth_identities" not in sql


def test_bind_identity_never_transfers_other_accounts_identity() -> None:
    cursor = MagicMock()
    cursor.fetchone.side_effect = [{"user_id": 8}]
    database = FakeDatabase(cursor)
    repository = PostgresOAuthIdentityRepository(database)

    result = repository.bind_identity(
        user_id=7, provider="github", provider_subject="subject-1"
    )

    assert result.status == "owned_by_other"
    sql = "\n".join(call.args[0] for call in cursor.execute.call_args_list)
    assert "INSERT INTO user_oauth_identities" not in sql
    assert "UPDATE user_oauth_identities" not in sql


def test_bind_identity_conflict_race_reports_actual_winner() -> None:
    # INSERT 被未走 advisory lock 的并发写入者抢占：重查属主并据实返回
    for winner_id, expected in ((8, "owned_by_other"), (7, "already_bound")):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, None, {"user_id": winner_id}]
        database = FakeDatabase(cursor)
        repository = PostgresOAuthIdentityRepository(database)

        result = repository.bind_identity(
            user_id=7, provider="github", provider_subject="subject-1"
        )

        assert result.status == expected


def test_bind_identity_rejects_unknown_provider_and_empty_subject() -> None:
    repository = PostgresOAuthIdentityRepository(FakeDatabase(MagicMock()))
    import pytest

    with pytest.raises(ValueError):
        repository.bind_identity(
            user_id=7, provider="gitlab", provider_subject="subject-1"
        )
    with pytest.raises(ValueError):
        repository.bind_identity(
            user_id=7, provider="github", provider_subject="   "
        )
