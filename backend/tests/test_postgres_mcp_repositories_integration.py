from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    create_postgres_pool,
)
from backend.app.core.postgres_migrations import PostgresMigrationRunner
from backend.app.repositories.mcp_server_repository import McpServerConfigConflictError
from backend.app.repositories.postgres_mcp_access_token_repository import (
    PostgresMcpAccessTokenRepository,
)
from backend.app.repositories.postgres_mcp_server_repository import (
    PostgresMcpServerConfigRepository,
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
            cursor.execute("TRUNCATE mcp_server_configs, users RESTART IDENTITY CASCADE")
    try:
        yield lifecycle
    finally:
        lifecycle.close()


def _create_user(database, email: str = "reader@example.com") -> int:
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (email, hashed_password, role)
                VALUES (%s, 'hash', 'user')
                RETURNING id
                """,
                (email,),
            )
            return int(cursor.fetchone()["id"])


def test_postgres_mcp_server_repository_round_trip_and_unique_sqlstate(database) -> None:
    repository = PostgresMcpServerConfigRepository(
        database,
        (("seeded", "Seeded MCP", " https://seeded.example/mcp "),),
    )

    seeded = repository.list_mcp_server_configs()
    assert len(seeded) == 1
    assert seeded[0]["url"] == "https://seeded.example/mcp"
    assert seeded[0]["auth_token"] is None

    created = repository.create_mcp_server_config(
        {
            "server_key": " Private ",
            "display_name": " Private MCP ",
            "description": " initial ",
            "url": " https://private.example/mcp ",
            "auth_type": " BEARER ",
            "auth_token": " top-secret ",
            "enabled": False,
        }
    )
    assert created["server_key"] == "private"
    assert created["auth_token"] == "top-secret"
    assert created["enabled"] is False
    assert created["created_at"].tzinfo is not None

    preserved = repository.update_mcp_server_config(
        created["id"],
        {"display_name": "Renamed", "auth_token": "  "},
    )
    assert preserved["display_name"] == "Renamed"
    assert preserved["auth_token"] == "top-secret"

    tested = repository.update_mcp_server_test_result(
        created["id"],
        {"status": " SUCCEEDED ", "message": " ready ", "tools": [{"name": "搜索"}]},
    )
    assert tested["last_test_status"] == "succeeded"
    assert tested["last_test_message"] == "ready"
    assert "搜索" in tested["last_tools_json"]
    assert tested["last_test_at"].tzinfo is not None

    cleared = repository.update_mcp_server_config(
        created["id"], {"clear_auth_token": True}
    )
    assert cleared["auth_token"] is None

    with pytest.raises(McpServerConfigConflictError):
        repository.create_mcp_server_config(
            {
                "server_key": "private",
                "display_name": "Duplicate",
                "url": "https://duplicate.example/mcp",
            }
        )

    assert repository.delete_mcp_server_config(created["id"])
    assert repository.get_mcp_server_config(created["id"]) is None
    assert not repository.delete_mcp_server_config(created["id"])


def test_postgres_mcp_token_lifecycle_secrecy_expiry_and_unique_sqlstate(database) -> None:
    repository = PostgresMcpAccessTokenRepository(database)
    user_id = _create_user(database)
    future = datetime.now(timezone.utc) + timedelta(hours=1)

    created = repository.create_user_mcp_token(
        user_id=user_id,
        token_hash="a" * 64,
        token_hint="aigc_mcp_abc...wxyz",
        scopes=["projects:favorites:read"],
        client_type="claude",
        client_label="Desktop",
        expires_at=future,
    )
    metadata = created["token_metadata"]
    assert created["replaced_count"] == 0
    assert metadata["scopes"] == ["projects:favorites:read"]
    assert metadata["created_at"].endswith("Z")
    assert metadata["expires_at"].endswith("Z")
    assert "token_hash" not in metadata

    listed = repository.list_user_mcp_tokens(user_id=user_id)
    assert listed == [metadata]
    assert "token_hash" not in listed[0]

    authenticated = repository.get_user_by_mcp_token_hash("a" * 64)
    assert authenticated["user_id"] == user_id
    assert authenticated["email"] == "reader@example.com"
    assert authenticated["scopes"] == ["projects:favorites:read"]
    assert "token_hash" not in authenticated

    with pytest.raises(Exception) as context:
        repository.create_user_mcp_token(
            user_id=user_id,
            token_hash="a" * 64,
            token_hint="duplicate",
            scopes=[],
            client_type="claude",
        )
    assert getattr(context.value, "sqlstate", None) == "23505"

    expired = repository.create_user_mcp_token(
        user_id=user_id,
        token_hash="b" * 64,
        token_hint="expired",
        scopes=[],
        client_type="claude",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert repository.get_user_by_mcp_token_hash("b" * 64) is None

    assert repository.delete_user_mcp_token(
        user_id=user_id,
        token_id=expired["token_metadata"]["id"],
    )
    assert not repository.delete_user_mcp_token(
        user_id=user_id,
        token_id=expired["token_metadata"]["id"],
    )
    assert repository.get_user_by_mcp_token_hash("b" * 64) is None
    assert all(item["id"] != expired["token_metadata"]["id"] for item in repository.list_user_mcp_tokens(user_id=user_id))


def test_postgres_mcp_token_rejects_missing_user(database) -> None:
    repository = PostgresMcpAccessTokenRepository(database)

    with pytest.raises(ValueError, match="user does not exist"):
        repository.create_user_mcp_token(
            user_id=999,
            token_hash="c" * 64,
            token_hint="missing",
            scopes=[],
            client_type="claude",
        )
