from __future__ import annotations

import os

import pytest

from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    create_postgres_pool,
)
from backend.app.core.postgres_migrations import PostgresMigrationRunner
from backend.app.repositories.postgres_user_account_repository import (
    PostgresUserAccountRepository,
)


pytestmark = pytest.mark.skipif(
    os.getenv("POSTGRES_INTEGRATION") != "1",
    reason="set POSTGRES_INTEGRATION=1 to run PostgreSQL integration tests",
)


@pytest.fixture
def database():
    lifecycle = PostgresDatabaseLifecycle(create_postgres_pool)
    lifecycle.open()
    PostgresMigrationRunner(lifecycle).apply()
    with lifecycle.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE users RESTART IDENTITY CASCADE")
    try:
        yield lifecycle
    finally:
        lifecycle.close()


def test_postgres_user_repository_round_trip_and_statistics(database) -> None:
    repository = PostgresUserAccountRepository(database)

    user_id = repository.create_user_with_email(
        "Reader@Example.COM",
        "hash-v1",
        invite_code_used="invite",
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
