from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from backend.app.core.config import Settings
from backend.app.domain.wechat_secret_box import WeChatSecretBox
from backend.app.repositories.mcp_access_token_repository import (
    McpAccessTokenRepository,
)
from backend.app.repositories.mcp_server_repository import McpServerConfigRepository
from backend.app.repositories.postgres_mcp_access_token_repository import (
    PostgresMcpAccessTokenRepository,
)
from backend.app.repositories.postgres_mcp_server_repository import (
    McpServerSecretError,
    PostgresMcpServerConfigRepository,
    _parse_sealed_envelope,
    build_mcp_server_secret_box,
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


def make_box() -> WeChatSecretBox:
    return WeChatSecretBox.generate_for_test()


def repository_with_cursor(repository_type, *args, secret_box: WeChatSecretBox | None = None):
    """默认给 server 仓储装配测试加密盒；显式 None 场景请直接构造。"""
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    if repository_type is PostgresMcpServerConfigRepository:
        return (
            repository_type(
                database,
                *args,
                secret_box=secret_box if secret_box is not None else make_box(),
            ),
            database,
            cursor,
        )
    return repository_type(database, *args), database, cursor


def sealed_str(box: WeChatSecretBox, plaintext: str) -> str:
    return json.dumps(box.seal(plaintext), ensure_ascii=False)


def unseal_arg(box: WeChatSecretBox, stored: str) -> str:
    envelope = _parse_sealed_envelope(stored)
    assert envelope is not None, f"expected sealed envelope, got: {stored!r}"
    return box.unseal(envelope)


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
    # 历史明文行兼容读取，原样下发
    assert result == [row]
    assert result[0] is not row
    assert database.transaction_count == 2


def test_server_create_normalizes_and_seals_secret() -> None:
    box = make_box()
    repository, _, cursor = repository_with_cursor(
        PostgresMcpServerConfigRepository, secret_box=box
    )
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
    # 密封往返：auth_token 落库为信封，可解密回原文，且不等于明文
    assert insert.args[1][:6] == (
        "example",
        "Example MCP",
        "Description",
        "https://example.test/mcp",
        "streamable_http",
        "bearer",
    )
    assert insert.args[1][7] is False
    assert unseal_arg(box, insert.args[1][6]) == "secret"
    assert "secret" not in insert.args[1][6]
    assert result == created


def test_server_create_without_token_stores_null() -> None:
    repository, _, cursor = repository_with_cursor(PostgresMcpServerConfigRepository)
    cursor.fetchone.side_effect = [
        {"id": 42},
        {"id": 42, "auth_token": None, "enabled": True},
    ]

    repository.create_mcp_server_config(
        {
            "server_key": "arxiv",
            "display_name": "Arxiv MCP",
            "url": "https://arxiv.example/mcp",
            "auth_type": "none",
            "auth_token": "ignored-when-none",
        }
    )

    insert = cursor.execute.call_args_list[0]
    assert insert.args[1][6] is None


def test_server_create_refuses_token_without_encryption_key() -> None:
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    repository = PostgresMcpServerConfigRepository(database, secret_box=None)

    with pytest.raises(McpServerSecretError):
        repository.create_mcp_server_config(
            {
                "server_key": "arxiv",
                "display_name": "Arxiv MCP",
                "url": "https://arxiv.example/mcp",
                "auth_type": "bearer",
                "auth_token": "secret",
            }
        )
    assert not any(
        "INSERT INTO mcp_server_configs" in call.args[0]
        for call in cursor.execute.call_args_list
    )


def test_server_get_decrypts_sealed_row() -> None:
    box = make_box()
    repository, _, cursor = repository_with_cursor(
        PostgresMcpServerConfigRepository, secret_box=box
    )
    cursor.fetchone.return_value = {
        "id": 42,
        "server_key": "example",
        "auth_token": sealed_str(box, "real-token"),
        "enabled": True,
    }

    result = repository.get_mcp_server_config(42)

    assert result is not None
    assert result["auth_token"] == "real-token"


def test_server_sealed_row_unreadable_without_key_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    box = make_box()
    ciphertext = sealed_str(box, "real-token")
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    repository = PostgresMcpServerConfigRepository(database, secret_box=None)
    cursor.fetchone.return_value = {
        "id": 42,
        "server_key": "example",
        "auth_token": ciphertext,
        "enabled": True,
    }

    with caplog.at_level(logging.WARNING):
        result = repository.get_mcp_server_config(42)

    # 绝不把密文当明文外发；表现为未设置 token 并记告警
    assert result is not None
    assert result["auth_token"] is None
    assert ciphertext != result["auth_token"]
    assert "无法解密封存的 auth_token" in caplog.text


def test_server_update_preserves_blank_secret_and_can_clear_it() -> None:
    box = make_box()
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
    repository, _, cursor = repository_with_cursor(
        PostgresMcpServerConfigRepository, secret_box=box
    )
    cursor.fetchone.side_effect = [existing, existing]

    repository.update_mcp_server_config(42, {"auth_token": "  "})
    # 历史明文保留值在写路径上立即密封迁移
    stored = cursor.execute.call_args_list[1].args[1][6]
    assert unseal_arg(box, stored) == "existing-secret"
    assert stored != "existing-secret"

    repository, _, cursor = repository_with_cursor(
        PostgresMcpServerConfigRepository, secret_box=box
    )
    cursor.fetchone.side_effect = [existing, existing]
    repository.update_mcp_server_config(42, {"clear_auth_token": True})
    assert cursor.execute.call_args_list[1].args[1][6] is None


def test_server_update_carries_existing_envelope_verbatim() -> None:
    box = make_box()
    sealed_token = sealed_str(box, "existing-secret")
    existing = {
        "id": 42,
        "server_key": "example",
        "display_name": "Example",
        "description": "Old",
        "url": "https://example.test/mcp",
        "transport": "streamable_http",
        "auth_type": "bearer",
        "auth_token": sealed_token,
        "enabled": True,
    }
    repository, _, cursor = repository_with_cursor(
        PostgresMcpServerConfigRepository, secret_box=box
    )
    cursor.fetchone.side_effect = [existing, existing]

    repository.update_mcp_server_config(42, {"description": "New"})

    update = cursor.execute.call_args_list[1]
    # 已密封信封原样携带，不重复加密封（nonce 不变，幂等可比对）
    assert update.args[1][6] == sealed_token


def test_server_update_seals_new_token() -> None:
    box = make_box()
    existing = {
        "id": 42,
        "server_key": "example",
        "display_name": "Example",
        "description": "Old",
        "url": "https://example.test/mcp",
        "transport": "streamable_http",
        "auth_type": "bearer",
        "auth_token": None,
        "enabled": True,
    }
    repository, _, cursor = repository_with_cursor(
        PostgresMcpServerConfigRepository, secret_box=box
    )
    cursor.fetchone.side_effect = [existing, existing]

    repository.update_mcp_server_config(42, {"auth_token": " new-secret "})

    update = cursor.execute.call_args_list[1]
    assert unseal_arg(box, update.args[1][6]) == "new-secret"


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
    # 读取投影补齐解密后的 auth_token 键（行内无 token 时为 None）
    assert result == {"id": 42, "last_test_status": "succeeded", "auth_token": None}


def test_mcp_server_box_builds_from_configured_settings() -> None:
    """密钥装配契约：合法配置产出按版本密封的加密盒。"""
    key = WeChatSecretBox.generate_key_material()
    config = Settings(
        _env_file=None,
        mcp_server_encryption_key=key,
        mcp_server_encryption_key_version="v2",
    )

    box = build_mcp_server_secret_box(config=config)

    assert box is not None
    assert box.seal("plain")["v"] == "v2"


def test_mcp_server_box_returns_none_when_key_missing_or_invalid() -> None:
    missing = Settings(_env_file=None, mcp_server_encryption_key="")
    assert build_mcp_server_secret_box(config=missing) is None

    invalid = Settings(_env_file=None, mcp_server_encryption_key="not-valid-base64!!!")
    assert build_mcp_server_secret_box(config=invalid) is None


def test_mcp_server_settings_reject_placeholder_and_bad_version() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="example placeholder"):
        Settings(_env_file=None, mcp_server_encryption_key="CHANGEME123")
    with pytest.raises(ValidationError, match="key_version"):
        Settings(_env_file=None, mcp_server_encryption_key_version="")
    with pytest.raises(ValidationError, match="key_version"):
        Settings(_env_file=None, mcp_server_encryption_key_version="a" * 65)


def test_token_create_locks_user_hides_hash_and_normalizes_timestamps() -> None:
    repository, _, cursor = repository_with_cursor(PostgresMcpAccessTokenRepository)
    created_at = datetime(2026, 7, 28, 1, 2, 3, tzinfo=timezone.utc)
    cursor.rowcount = 0  # 封顶淘汰：无超额 token
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

    lock, purge, insert, evict, select = cursor.execute.call_args_list
    assert "FOR UPDATE" in lock.args[0]
    assert "revoked_at IS NOT NULL" in purge.args[0]
    assert "RETURNING id" in insert.args[0]
    # 封顶淘汰：保留最新 max_active_tokens 个活跃 token（默认 20）
    assert "OFFSET %s" in evict.args[0]
    assert "ORDER BY created_at DESC, id DESC" in evict.args[0]
    assert evict.args[1] == (7, 7, 20)
    assert "token_hash" not in select.args[0]
    assert result["replaced_count"] == 0
    assert result["token_metadata"]["scopes"] == ["projects:favorites:read"]
    assert result["token_metadata"]["created_at"] == "2026-07-28T01:02:03Z"
    assert "token_hash" not in result["token_metadata"]


def test_token_create_reports_real_eviction_count_beyond_cap() -> None:
    repository, _, cursor = repository_with_cursor(PostgresMcpAccessTokenRepository)
    cursor.rowcount = 3  # 超额 3 个最旧活跃 token 被同事务软淘汰
    cursor.fetchone.side_effect = [
        {"id": 7},
        {"id": 21},
        {"id": 21, "user_id": 7, "scopes_json": "[]"},
    ]

    result = repository.create_user_mcp_token(
        user_id=7,
        token_hash="a" * 64,
        token_hint="hint",
        scopes=[],
        client_type="claude",
    )

    evict = cursor.execute.call_args_list[3]
    assert "revoked_at = COALESCE" in evict.args[0]
    assert "deleted_at = CURRENT_TIMESTAMP" in evict.args[0]
    assert result["replaced_count"] == 3


def test_token_cap_is_clamped_to_at_least_one() -> None:
    repository, _, _ = repository_with_cursor(
        PostgresMcpAccessTokenRepository, 0
    )
    assert repository._max_active_tokens == 1


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

    lookup = cursor.execute.call_args_list[0]
    assert "t.token_hash = %s" in lookup.args[0]
    assert "t.revoked_at IS NULL" in lookup.args[0]
    assert "t.deleted_at IS NULL" in lookup.args[0]
    assert "t.expires_at > CURRENT_TIMESTAMP" in lookup.args[0]
    # 禁用账号的未吊销 token 必须一并失效（REST JWT 路径已有 per-request 拦截，
    # MCP token 路径曾缺失该校验，渗透实测禁用后 tools/list 仍 200）
    assert "u.disabled = FALSE" in lookup.args[0]
    # 坏 scope 不应更新 last_used_at；否则每次无效认证都会制造写放大。
    assert len(cursor.execute.call_args_list) == 1
    assert result["scopes"] is None
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
