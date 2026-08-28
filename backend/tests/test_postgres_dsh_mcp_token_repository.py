"""PostgreSQL DSH MCP token 仓储契约测试。

覆盖：
  - ensure：用户行 FOR UPDATE 串行化；已有密封活跃 DSH token 直接解密回显
    （reused，不 INSERT——重复 ensure/并发 ensure 不得互相吊销）；无则
    INSERT（created，回环解密验证密钥往返）；只有 legacy hash-only 行时
    recovery_required（不静默吊销仍在使用的旧 token）；
  - rotate：单事务吊销全部活跃 DSH 行（含 legacy，不碰 generic）+ 签发新
    token，revoked_count 为真实吊销数；
  - 密封材料边界：对外 metadata 永不携带 token_encrypted/token_hash；
    无密钥或密文损坏时抛 DshMcpTokenSecretError（绝不回显密文）；
  - generic create 显式写 purpose='generic'（与 DSH 行互不干扰）；
  - 加密盒装配：合法配置产盒、缺省/非法返回 None、占位符/非法版本被
    Settings 校验拒绝。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from backend.app.core.config import Settings
from backend.app.domain.wechat_secret_box import WeChatSecretBox
from backend.app.repositories.mcp_access_token_repository import DshMcpTokenManager
from backend.app.repositories.postgres_mcp_access_token_repository import (
    DshMcpTokenSecretError,
    PostgresMcpAccessTokenRepository,
    build_dsh_mcp_token_secret_box,
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


# repository_with_cursor 的缺省哨兵：默认装配测试加密盒，显式 None 走无密钥路径
_SECRET_BOX_DEFAULT: Any = object()


def repository_with_cursor(
    *, secret_box: WeChatSecretBox | None = _SECRET_BOX_DEFAULT
) -> tuple[PostgresMcpAccessTokenRepository, FakeDatabase, MagicMock]:
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    repository = PostgresMcpAccessTokenRepository(
        database,
        secret_box=make_box() if secret_box is _SECRET_BOX_DEFAULT else secret_box,
    )
    return repository, database, cursor


def sealed_str(box: WeChatSecretBox, plaintext: str) -> str:
    return json.dumps(box.seal(plaintext), ensure_ascii=False)


def _material(box: WeChatSecretBox) -> dict[str, Any]:
    return {
        "token_hash": "a" * 64,
        "token_hint": "aigc_mcp_abc...wxyz",
        "token_encrypted": sealed_str(box, "aigc_mcp_plaintext"),
        "scopes": ["projects:favorites:read"],
        "client_type": "other",
        "client_label": "dsh-aigc-radar",
    }


def _dsh_row(box: WeChatSecretBox, *, sealed: bool = True) -> dict[str, Any]:
    return {
        "id": 21,
        "user_id": 7,
        "token_hint": "aigc_mcp_abc...wxyz",
        "scopes_json": '["projects:favorites:read"]',
        "client_type": "other",
        "client_label": "dsh-aigc-radar",
        "expires_at": None,
        "revoked_at": None,
        "deleted_at": None,
        "created_at": datetime(2026, 8, 28, 1, 2, 3, tzinfo=timezone.utc),
        "last_used_at": None,
        "purpose": "dsh",
        "token_encrypted": sealed_str(box, "aigc_mcp_plaintext") if sealed else None,
    }


def test_repository_exposes_dsh_token_contract() -> None:
    repository, _, _ = repository_with_cursor()
    contract: DshMcpTokenManager = repository
    assert callable(contract.ensure_user_dsh_mcp_token)
    assert callable(contract.rotate_user_dsh_mcp_token)


def test_ensure_reuses_sealed_active_token_without_insert() -> None:
    box = make_box()
    repository, database, cursor = repository_with_cursor(secret_box=box)
    cursor.fetchone.side_effect = [{"id": 7}]
    cursor.fetchall.return_value = [_dsh_row(box)]

    result = repository.ensure_user_dsh_mcp_token(user_id=7, **_material(box))

    lock, select = cursor.execute.call_args_list
    assert "FOR UPDATE" in lock.args[0]
    assert lock.args[1] == (7,)
    assert "purpose = %s" in select.args[0]
    assert select.args[1] == (7, "dsh")
    assert "revoked_at IS NULL" in select.args[0]
    assert "deleted_at IS NULL" in select.args[0]
    # 密封行优先排序：并发/重复 ensure 回显同一枚
    assert "token_encrypted IS NOT NULL" in select.args[0]
    # ensure 幂等：已持活跃密封 token 不得 INSERT，也不得吊销任何行
    assert not any(
        "INSERT INTO user_mcp_tokens" in call.args[0]
        for call in cursor.execute.call_args_list
    )
    assert not any(
        "UPDATE user_mcp_tokens" in call.args[0]
        for call in cursor.execute.call_args_list
    )
    assert database.transaction_count == 1
    assert result["status"] == "reused"
    assert result["token"] == "aigc_mcp_plaintext"
    metadata = result["token_metadata"]
    assert metadata["purpose"] == "dsh"
    assert metadata["scopes"] == ["projects:favorites:read"]
    assert metadata["created_at"] == "2026-08-28T01:02:03Z"
    assert "token_encrypted" not in metadata
    assert "token_hash" not in metadata
    assert "scopes_json" not in metadata


def test_ensure_creates_and_roundtrips_when_no_dsh_row() -> None:
    box = make_box()
    repository, database, cursor = repository_with_cursor(secret_box=box)
    material = _material(box)
    cursor.fetchone.side_effect = [{"id": 7}, _dsh_row(box)]
    cursor.fetchall.return_value = []

    result = repository.ensure_user_dsh_mcp_token(user_id=7, **material)

    lock, _select, insert = cursor.execute.call_args_list
    assert "FOR UPDATE" in lock.args[0]
    assert "INSERT INTO user_mcp_tokens" in insert.args[0]
    # expires_at 恒 NULL（DSH token 不设过期，随用户显式 rotate 吊销）
    assert "NULL, %s, %s" in insert.args[0]
    assert insert.args[1] == (
        7,
        material["token_hash"],
        material["token_hint"],
        '["projects:favorites:read"]',
        "other",
        "dsh-aigc-radar",
        "dsh",
        material["token_encrypted"],
    )
    assert database.transaction_count == 1
    assert result["status"] == "created"
    # 回环解密：落库信封必须能解回外发明文（密钥漂移立即暴露）
    assert result["token"] == "aigc_mcp_plaintext"
    assert "token_encrypted" not in result["token_metadata"]


def test_ensure_legacy_hash_only_rows_return_recovery_required() -> None:
    box = make_box()
    repository, database, cursor = repository_with_cursor(secret_box=box)
    cursor.fetchone.side_effect = [{"id": 7}]
    cursor.fetchall.return_value = [_dsh_row(box, sealed=False), _dsh_row(box, sealed=False)]

    result = repository.ensure_user_dsh_mcp_token(user_id=7, **_material(box))

    # legacy 行无法回显明文；绝不静默吊销用户机器上可能仍在使用的旧 token
    assert result == {"status": "recovery_required", "legacy_count": 2}
    assert not any(
        "INSERT INTO user_mcp_tokens" in call.args[0]
        for call in cursor.execute.call_args_list
    )
    assert database.transaction_count == 1


def test_ensure_prefers_sealed_row_over_legacy_rows() -> None:
    box = make_box()
    repository, _, cursor = repository_with_cursor(secret_box=box)
    cursor.fetchone.side_effect = [{"id": 7}]
    cursor.fetchall.return_value = [_dsh_row(box, sealed=False), _dsh_row(box)]

    result = repository.ensure_user_dsh_mcp_token(user_id=7, **_material(box))

    assert result["status"] == "reused"
    assert result["token"] == "aigc_mcp_plaintext"


def test_ensure_rejects_missing_user_before_any_write() -> None:
    box = make_box()
    repository, _, cursor = repository_with_cursor(secret_box=box)
    cursor.fetchone.return_value = None

    with pytest.raises(ValueError, match="user does not exist"):
        repository.ensure_user_dsh_mcp_token(user_id=7, **_material(box))

    assert cursor.execute.call_count == 1


def test_ensure_without_key_raises_and_never_echoes_ciphertext() -> None:
    box = make_box()
    repository, _, cursor = repository_with_cursor(secret_box=None)
    cursor.fetchone.side_effect = [{"id": 7}]
    cursor.fetchall.return_value = [_dsh_row(box)]

    with pytest.raises(DshMcpTokenSecretError):
        repository.ensure_user_dsh_mcp_token(user_id=7, **_material(box))


def test_ensure_corrupt_envelope_raises_secret_error() -> None:
    box = make_box()
    repository, _, cursor = repository_with_cursor(secret_box=box)
    cursor.fetchone.side_effect = [{"id": 7}]
    corrupt = _dsh_row(box)
    corrupt["token_encrypted"] = "not-a-json-envelope"
    cursor.fetchall.return_value = [corrupt]

    with pytest.raises(DshMcpTokenSecretError):
        repository.ensure_user_dsh_mcp_token(user_id=7, **_material(box))


def test_ensure_wrong_key_envelope_raises_secret_error() -> None:
    sealing_box = make_box()
    other_box = make_box()
    repository, _, cursor = repository_with_cursor(secret_box=other_box)
    cursor.fetchone.side_effect = [{"id": 7}]
    cursor.fetchall.return_value = [_dsh_row(sealing_box)]

    with pytest.raises(DshMcpTokenSecretError):
        repository.ensure_user_dsh_mcp_token(user_id=7, **_material(sealing_box))


def test_rotate_revokes_only_dsh_rows_then_inserts_in_single_transaction() -> None:
    box = make_box()
    repository, database, cursor = repository_with_cursor(secret_box=box)
    material = _material(box)
    cursor.rowcount = 2  # 1 密封行 + 1 legacy 行（partial unique 之外的存量）
    cursor.fetchone.side_effect = [{"id": 7}, _dsh_row(box)]

    result = repository.rotate_user_dsh_mcp_token(user_id=7, **material)

    lock, revoke, insert = cursor.execute.call_args_list
    assert "FOR UPDATE" in lock.args[0]
    assert "UPDATE user_mcp_tokens" in revoke.args[0]
    assert "purpose = %s" in revoke.args[0]
    # 吊销范围仅 purpose='dsh'：generic token 不受 rotate 影响
    assert revoke.args[1] == (7, "dsh")
    assert "deleted_at IS NULL" in revoke.args[0]
    assert "INSERT INTO user_mcp_tokens" in insert.args[0]
    assert insert.args[1][-2] == "dsh"
    # 吊销 + 签发必须在同一事务：任何一步失败整体回滚，不出现无 token 空窗
    assert database.transaction_count == 1
    assert result["status"] == "rotated"
    assert result["revoked_count"] == 2
    assert result["token"] == "aigc_mcp_plaintext"
    assert "token_encrypted" not in result["token_metadata"]


def test_generic_create_writes_generic_purpose_and_strips_secrets() -> None:
    """0064 加列回归：通用创建显式写 purpose='generic'，metadata 不泄露
    hash/密封材料；DSH ensure/rotate 与通用生命周期互不干扰。"""
    repository, _, cursor = repository_with_cursor(secret_box=None)
    cursor.rowcount = 0
    cursor.fetchone.side_effect = [
        {"id": 7},
        {"id": 9},
        {
            "id": 9,
            "user_id": 7,
            "token_hint": "aigc_mcp_abc...wxyz",
            "scopes_json": '["projects:favorites:read"]',
            "client_type": "other",
            "client_label": "my-client",
            "expires_at": None,
            "revoked_at": None,
            "deleted_at": None,
            "created_at": None,
            "last_used_at": None,
        },
    ]

    result = repository.create_user_mcp_token(
        user_id=7,
        token_hash="b" * 64,
        token_hint="aigc_mcp_abc...wxyz",
        scopes=["projects:favorites:read"],
        client_type="other",
        client_label="my-client",
    )

    insert = next(
        call
        for call in cursor.execute.call_args_list
        if "INSERT INTO user_mcp_tokens" in call.args[0]
    )
    assert "purpose" in insert.args[0]
    assert insert.args[1][-1] == "generic"
    assert "token_encrypted" not in result["token_metadata"]
    assert "token_hash" not in result["token_metadata"]


def test_dsh_box_builds_from_configured_settings() -> None:
    """密钥装配契约：合法配置产出按版本密封的加密盒（独立密钥域）。"""
    key = WeChatSecretBox.generate_key_material()
    config = Settings(
        _env_file=None,
        dsh_mcp_token_encryption_key=key,
        dsh_mcp_token_encryption_key_version="v2",
    )

    box = build_dsh_mcp_token_secret_box(config=config)

    assert box is not None
    assert box.seal("plain")["v"] == "v2"


def test_dsh_box_returns_none_when_key_missing_or_invalid() -> None:
    missing = Settings(_env_file=None, dsh_mcp_token_encryption_key="")
    assert build_dsh_mcp_token_secret_box(config=missing) is None

    invalid = Settings(_env_file=None, dsh_mcp_token_encryption_key="not-valid-base64!!!")
    assert build_dsh_mcp_token_secret_box(config=invalid) is None


def test_dsh_settings_reject_placeholder_and_bad_version() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="example placeholder"):
        Settings(_env_file=None, dsh_mcp_token_encryption_key="CHANGEME123")
    with pytest.raises(ValidationError, match="key_version"):
        Settings(_env_file=None, dsh_mcp_token_encryption_key_version="")
    with pytest.raises(ValidationError, match="key_version"):
        Settings(_env_file=None, dsh_mcp_token_encryption_key_version="a" * 65)
