from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from backend.app.repositories.mcp_access_token_repository import (
    McpAccessTokenRepository,
)
from backend.app.repositories.mcp_server_repository import McpServerConfigRepository
from backend.app.repositories.postgres_mcp_access_token_repository import (
    PostgresMcpAccessTokenRepository,
)
from backend.app.repositories.postgres_mcp_server_repository import (
    PostgresMcpServerConfigRepository,
)


class FakeDatabase:
    def __init__(self, cursor: MagicMock) -> None:
        self.cursor = cursor
        self.connection = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        self.connection.cursor.return_value = cursor_context
        self.transaction_count = 0

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        yield self.connection


def repository_with_cursor(repository_type, *args):
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    return repository_type(database, *args), database, cursor


def test_postgres_adapters_expose_repository_contracts() -> None:
    server, _, _ = repository_with_cursor(PostgresMcpServerConfigRepository)
    token, _, _ = repository_with_cursor(PostgresMcpAccessTokenRepository)

    server_contract: McpServerConfigRepository = server
    token_contract: McpAccessTokenRepository = token

    assert callable(server_contract.update_mcp_server_test_result)
    assert callable(token_contract.get_user_by_mcp_token_hash)


def test_server_seed_uses_conflict_handling_and_list_preserves_secret_shape() -> None:
    repository, database, cursor = repository_with_cursor(
        PostgresMcpServerConfigRepository,
        (
            ("arxiv", "Arxiv MCP", " https://arxiv.example/mcp "),
            ("github", "GitHub MCP", "  "),
        ),
    )
    row = {"id": 42, "auth_token": "internal-token", "enabled": True}
    cursor.fetchall.return_value = [row]

    result = repository.list_mcp_server_configs()

    seed, listing = cursor.execute.call_args_list
    assert "ON CONFLICT (server_key) DO NOTHING" in seed.args[0]
    assert seed.args[1][-1] == "https://arxiv.example/mcp"
    assert "auth_type, auth_token, enabled" in listing.args[0]
    assert "ORDER BY enabled DESC, display_name ASC, id ASC" in listing.args[0]
    assert result == [row]
    assert result[0] is not row
    assert database.transaction_count == 2


def test_server_create_normalizes_and_uses_returning() -> None:
    repository, _, cursor = repository_with_cursor(PostgresMcpServerConfigRepository)
    created = {"id": 42, "auth_token": "secret", "enabled": False}
    cursor.fetchone.side_effect = [{"id": 42}, created]

    result = repository.create_mcp_server_config(
        {
            "server_key": " Example ",
            "display_name": " Example MCP ",
            "description": " Description ",
            "url": " https://example.test/mcp ",
            "transport": " STREAMABLE_HTTP ",
            "auth_type": " BEARER ",
            "auth_token": " secret ",
            "enabled": False,
        }
    )

    insert = cursor.execute.call_args_list[0]
    assert "RETURNING id" in insert.args[0]
    assert insert.args[1] == (
        "example",
        "Example MCP",
        "Description",
        "https://example.test/mcp",
        "streamable_http",
        "bearer",
        "secret",
        False,
    )
    assert result == created


def test_server_update_preserves_blank_secret_and_can_clear_it() -> None:
    existing = {
        "id": 42,
        "server_key": "example",
        "display_name": "Example",
        "description": "Old",
        "url": "https://example.test/mcp",
        "transport": "streamable_http",
        "auth_type": "bearer",
        "auth_token": "existing-secret",
        "enabled": True,
    }
    repository, _, cursor = repository_with_cursor(PostgresMcpServerConfigRepository)
    cursor.fetchone.side_effect = [existing, existing]

    repository.update_mcp_server_config(42, {"auth_token": "  "})
    assert cursor.execute.call_args_list[1].args[1][6] == "existing-secret"

    repository, _, cursor = repository_with_cursor(PostgresMcpServerConfigRepository)
    cursor.fetchone.side_effect = [existing, existing]
    repository.update_mcp_server_config(42, {"clear_auth_token": True})
    assert cursor.execute.call_args_list[1].args[1][6] is None


def test_server_mutations_are_parameterized_and_serialize_unicode_tools() -> None:
    repository, _, cursor = repository_with_cursor(PostgresMcpServerConfigRepository)
    cursor.rowcount = 1
    cursor.fetchone.return_value = {"id": 42, "last_test_status": "succeeded"}

    assert repository.delete_mcp_server_config(7)
    assert cursor.execute.call_args.args == (
        "DELETE FROM mcp_server_configs WHERE id = %s",
        (7,),
    )

    result = repository.update_mcp_server_test_result(
        42,
        {"status": " SUCCEEDED ", "message": " ready ", "tools": [{"name": "搜索"}]},
    )
    update = cursor.execute.call_args_list[1]
    assert update.args[1][0:2] == ("succeeded", "ready")
    assert "搜索" in update.args[1][2]
    assert result == {"id": 42, "last_test_status": "succeeded"}


def test_token_create_locks_user_hides_hash_and_normalizes_timestamps() -> None:
    repository, _, cursor = repository_with_cursor(PostgresMcpAccessTokenRepository)
    created_at = datetime(2026, 7, 28, 1, 2, 3, tzinfo=timezone.utc)
    cursor.fetchone.side_effect = [
        {"id": 7},
        {"id": 21},
        {
            "id": 21,
            "user_id": 7,
            "token_hint": "hint",
            "scopes_json": '["projects:favorites:read"]',
            "created_at": created_at,
        },
    ]

    result = repository.create_user_mcp_token(
        user_id=7,
        token_hash="a" * 64,
        token_hint="hint",
        scopes=["projects:favorites:read"],
        client_type="claude",
    )

    lock, purge, insert, select = cursor.execute.call_args_list
    assert "FOR UPDATE" in lock.args[0]
    assert "revoked_at IS NOT NULL" in purge.args[0]
    assert "RETURNING id" in insert.args[0]
    assert "token_hash" not in select.args[0]
    assert result["replaced_count"] == 0
    assert result["token_metadata"]["scopes"] == ["projects:favorites:read"]
    assert result["token_metadata"]["created_at"] == "2026-07-28T01:02:03Z"
    assert "token_hash" not in result["token_metadata"]


def test_token_create_rejects_missing_user_before_insert() -> None:
    repository, _, cursor = repository_with_cursor(PostgresMcpAccessTokenRepository)
    cursor.fetchone.return_value = None

    with pytest.raises(ValueError, match="user does not exist"):
        repository.create_user_mcp_token(
            user_id=7,
            token_hash="a" * 64,
            token_hint="hint",
            scopes=[],
            client_type="claude",
        )

    assert cursor.execute.call_count == 1


def test_token_lookup_filters_inactive_and_throttles_last_use() -> None:
    repository, _, cursor = repository_with_cursor(PostgresMcpAccessTokenRepository)
    cursor.fetchone.return_value = {
        "token_id": 21,
        "user_id": 7,
        "scopes_json": "not-json",
        "email": "reader@example.com",
        "role": "user",
    }

    result = repository.get_user_by_mcp_token_hash("a" * 64)

    lookup, update = cursor.execute.call_args_list
    assert "t.token_hash = %s" in lookup.args[0]
    assert "t.revoked_at IS NULL" in lookup.args[0]
    assert "t.deleted_at IS NULL" in lookup.args[0]
    assert "t.expires_at > CURRENT_TIMESTAMP" in lookup.args[0]
    assert "INTERVAL '5 minutes'" in update.args[0]
    assert result["scopes"] == []
    assert "token_hash" not in result


def test_token_list_and_delete_remain_owner_scoped() -> None:
    repository, _, cursor = repository_with_cursor(PostgresMcpAccessTokenRepository)
    cursor.fetchall.return_value = []

    assert repository.list_user_mcp_tokens(user_id=7) == []
    listing = cursor.execute.call_args
    assert "user_id = %s" in listing.args[0]
    assert "revoked_at IS NULL AND deleted_at IS NULL" in listing.args[0]
    assert listing.args[1] == (7,)

    cursor.rowcount = 1
    assert repository.delete_user_mcp_token(user_id=7, token_id=21)
    deletion = cursor.execute.call_args
    assert "revoked_at = COALESCE" in deletion.args[0]
    assert "user_id = %s AND deleted_at IS NULL" in deletion.args[0]
    assert deletion.args[1] == (21, 7)
