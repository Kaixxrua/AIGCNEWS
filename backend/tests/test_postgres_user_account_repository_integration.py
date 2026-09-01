from __future__ import annotations

import pytest

from backend.app.repositories.postgres_user_account_repository import (
    PostgresUserAccountRepository,
)
from backend.tests.postgres_test_safety import postgres_test_sandbox


@pytest.fixture
def database():
    with postgres_test_sandbox() as sandbox:
        yield sandbox.database


def test_postgres_user_repository_round_trip_and_statistics(database) -> None:
    repository = PostgresUserAccountRepository(database)

    user_id = repository.create_user_with_email(
        "Reader@Example.COM",
        "hash-v1",
        username="reader",
    )

    assert user_id == 1
    row = repository.get_user_by_email("READER@example.com")
    assert row is not None
    assert row["id"] == 1
    assert row["email"] == "reader@example.com"
    assert row["hashed_password"] == "hash-v1"
    assert repository.get_user_count() == 1
    assert repository.get_today_registered_user_count() == 1
    assert (
        repository.update_user_password(
            user_id=user_id,
            email="READER@example.com",
            hashed_password="hash-v2",
        )
        == 1
    )
    assert repository.get_user_by_email("reader@example.com")["hashed_password"] == "hash-v2"


def test_postgres_user_repository_preserves_phone_path_and_unique_email(database) -> None:
    repository = PostgresUserAccountRepository(database)

    phone_id = repository.create_user("13800000000", "phone-user", "hash")
    assert repository.get_user_by_phone("13800000000")["id"] == phone_id

    repository.create_user_with_email("unique@example.com", "hash")
    with pytest.raises(Exception) as context:
        repository.create_user_with_email("unique@example.com", "other-hash")
    assert getattr(context.value, "sqlstate", None) == "23505"
    assert repository.get_user_count() == 2


def test_postgres_get_user_by_id_projects_disabled_flag(database) -> None:
    """auth.get_current_user 依赖 record['disabled'] 判定停用账号（迁移 0029 补列）。"""
    repository = PostgresUserAccountRepository(database)
    user_id = repository.create_user_with_email("flag@example.com", "hash")

    row = repository.get_user_by_id(user_id)
    assert row is not None
    assert row["disabled"] is False

    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE users SET disabled = TRUE WHERE id = %s", (user_id,))

    assert repository.get_user_by_id(user_id)["disabled"] is True
