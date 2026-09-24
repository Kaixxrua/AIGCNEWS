from __future__ import annotations

import uuid

import pytest

from backend.app.repositories.postgres_oauth_identity_repository import (
    PostgresOAuthIdentityRepository,
)
from backend.tests.postgres_test_safety import postgres_test_sandbox


@pytest.fixture
def database():
    with postgres_test_sandbox() as sandbox:
        yield sandbox.database


def _login(repository: PostgresOAuthIdentityRepository, subject: str, email: str):
    return repository.resolve_first_login(
        provider="github", provider_subject=subject,
        display_email=email, email_verified=True, username="octocat",
    )


def test_returning_oauth_login_resolves_the_same_user_id(database) -> None:
    """回调用 user["id"] 签发 handoff：已绑定身份的再次登录也必须带 users.id。"""
    repository = PostgresOAuthIdentityRepository(database)
    email = f"oauth-{uuid.uuid4().hex}@example.com"

    first = _login(repository, "1001", email)
    returning = _login(repository, "1001", email)

    assert first.status == returning.status == "authenticated"
    assert isinstance(first.user["id"], int)
    assert returning.user["id"] == returning.user["user_id"] == first.user["id"]
    assert isinstance(returning.user["identity_id"], int)


def test_returning_login_linked_to_verified_password_account(database) -> None:
    repository = PostgresOAuthIdentityRepository(database)
    email = f"linked-{uuid.uuid4().hex}@example.com"
    with database.transaction() as connection:
        owner_id = int(connection.execute(
            "INSERT INTO users (email, hashed_password, email_verified) VALUES (%s, 'hash', TRUE) RETURNING id",
            (email,),
        ).fetchone()["id"])

    assert _login(repository, "2002", email).user["id"] == owner_id
    assert _login(repository, "2002", email).user["id"] == owner_id


def test_returning_login_of_disabled_user_still_identifies_the_user(database) -> None:
    repository = PostgresOAuthIdentityRepository(database)
    email = f"disabled-{uuid.uuid4().hex}@example.com"
    user_id = _login(repository, "3003", email).user["id"]
    with database.transaction() as connection:
        connection.execute("UPDATE users SET disabled = TRUE WHERE id = %s", (user_id,))

    returning = _login(repository, "3003", email)

    assert returning.status == "disabled"
    assert returning.user["id"] == user_id


def test_only_the_login_that_inserts_the_account_reports_created(database) -> None:
    """首登资料导入以 created 为门：只有真正新建账户的那次登录为真。"""
    repository = PostgresOAuthIdentityRepository(database)
    email = f"created-{uuid.uuid4().hex}@example.com"
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO users (email, hashed_password, email_verified) VALUES (%s, 'hash', TRUE)",
            (email,),
        )

    new_account = _login(repository, "4004", f"fresh-{uuid.uuid4().hex}@example.com")
    returning = _login(repository, "4004", "ignored@example.com")
    linked_to_existing = _login(repository, "5005", email)

    assert new_account.created is True
    assert returning.created is False
    assert linked_to_existing.created is False
    with database.transaction() as connection:
        username = connection.execute(
            "SELECT username FROM users WHERE id = %s", (new_account.user["id"],)
        ).fetchone()["username"]
    assert username == "octocat"
