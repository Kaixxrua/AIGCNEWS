"""PostgreSQL feed token 仓储契约测试。

覆盖：
  - get_or_create：用户行 FOR UPDATE 串行化；已持活跃 token 直接解密回显
    （GET 幂等，并发 GET 不得互相吊销）；无则 INSERT；
  - rotate：单事务吊销旧 + 签发新，revoked_count 为真实吊销数；
  - hash 查询：吊销/禁用 fail-closed，透出会员档位字段，last_used_at
    1 小时节流（RSS 轮询频率高于 MCP，5 分钟窗口会写放大）；
  - 加密盒装配：合法配置产盒、缺省/非法返回 None、占位符/非法版本被
    Settings 校验拒绝；无密钥时读侧抛 FeedTokenSecretError（绝不回显密文）。
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
from backend.app.repositories.feed_token_repository import FeedTokenRepository
from backend.app.repositories.postgres_feed_token_repository import (
    FeedTokenSecretError,
    PostgresFeedTokenRepository,
    build_feed_token_secret_box,
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
) -> tuple[PostgresFeedTokenRepository, FakeDatabase, MagicMock]:
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    repository = PostgresFeedTokenRepository(
        database,
        secret_box=make_box() if secret_box is _SECRET_BOX_DEFAULT else secret_box,
    )
    return repository, database, cursor


def sealed_str(box: WeChatSecretBox, plaintext: str) -> str:
    return json.dumps(box.seal(plaintext), ensure_ascii=False)


def _material(box: WeChatSecretBox) -> dict[str, str]:
    return {
        "token_hash": "a" * 64,
        "token_hint": "aigc_feed_abc...wxyz",
        "token_encrypted": sealed_str(box, "aigc_feed_plaintext"),
    }


def test_repository_exposes_feed_token_contract() -> None:
    repository, _, _ = repository_with_cursor()
    contract: FeedTokenRepository = repository
    assert callable(contract.get_or_create_feed_token)
    assert callable(contract.rotate_feed_token)
    assert callable(contract.get_user_by_feed_token_hash)


def test_get_or_create_returns_existing_active_token_without_insert() -> None:
    box = make_box()
    repository, database, cursor = repository_with_cursor(secret_box=box)
    created_at = datetime(2026, 8, 20, 1, 2, 3, tzinfo=timezone.utc)
    cursor.fetchone.side_effect = [
        {"id": 7},
        {
            "id": 21,
            "user_id": 7,
            "token_hint": "aigc_feed_abc...wxyz",
            "token_encrypted": sealed_str(box, "aigc_feed_plaintext"),
            "created_at": created_at,
            "last_used_at": None,
        },
    ]

    result = repository.get_or_create_feed_token(user_id=7, **_material(box))

    lock, select = cursor.execute.call_args_list
    assert "FOR UPDATE" in lock.args[0]
    assert "FROM user_feed_tokens" in select.args[0]
    assert "revoked_at IS NULL" in select.args[0]
    # GET 幂等：已持活跃 token 不得 INSERT（并发 GET 不得互相吊销）
    assert not any(
        "INSERT INTO user_feed_tokens" in call.args[0]
        for call in cursor.execute.call_args_list
    )
    assert database.transaction_count == 1
    assert result["token"] == "aigc_feed_plaintext"
    assert result["created"] is False
    assert result["created_at"] == "2026-08-20T01:02:03Z"
    assert "token_hash" not in result
    assert "token_encrypted" not in result


def test_get_or_create_inserts_when_no_active_token() -> None:
    box = make_box()
    repository, _, cursor = repository_with_cursor(secret_box=box)
    material = _material(box)
    created_at = datetime(2026, 8, 25, 8, 0, 0, tzinfo=timezone.utc)
    cursor.fetchone.side_effect = [
        {"id": 7},
        None,
        {
            "id": 22,
            "user_id": 7,
            "token_hint": material["token_hint"],
            "token_encrypted": material["token_encrypted"],
            "created_at": created_at,
        },
    ]

    result = repository.get_or_create_feed_token(user_id=7, **material)

    lock, select, insert = cursor.execute.call_args_list
    assert "FOR UPDATE" in lock.args[0]
    assert "RETURNING id" in insert.args[0]
    assert insert.args[1] == (
        7,
        material["token_hash"],
        material["token_hint"],
        material["token_encrypted"],
    )
    assert result["created"] is True
    assert result["token"] == "aigc_feed_plaintext"
    assert result["created_at"] == "2026-08-25T08:00:00Z"


def test_get_or_create_rejects_missing_user_before_insert() -> None:
    box = make_box()
    repository, _, cursor = repository_with_cursor(secret_box=box)
    cursor.fetchone.return_value = None

    with pytest.raises(ValueError, match="user does not exist"):
        repository.get_or_create_feed_token(user_id=7, **_material(box))

    assert cursor.execute.call_count == 1


def test_rotate_revokes_active_then_inserts_in_single_transaction() -> None:
    box = make_box()
    repository, database, cursor = repository_with_cursor(secret_box=box)
    material = _material(box)
    cursor.rowcount = 2  # 脏数据下吊销 2 行（partial unique 常态应只有 1 行活跃）
    cursor.fetchone.side_effect = [
        {"id": 7},
        {
            "id": 23,
            "user_id": 7,
            "token_hint": material["token_hint"],
            "token_encrypted": material["token_encrypted"],
            "created_at": None,
        },
    ]

    result = repository.rotate_feed_token(user_id=7, **material)

    lock, revoke, insert = cursor.execute.call_args_list
    assert "FOR UPDATE" in lock.args[0]
    assert "SET revoked_at = CURRENT_TIMESTAMP" in revoke.args[0]
    assert "revoked_at IS NULL" in revoke.args[0]
    assert revoke.args[1] == (7,)
    assert "INSERT INTO user_feed_tokens" in insert.args[0]
    # 吊销 + 签发必须在同一事务：任何一步失败整体回滚，不出现无 token 空窗
    assert database.transaction_count == 1
    assert result["revoked_count"] == 2
    assert result["created"] is True
    assert result["token"] == "aigc_feed_plaintext"


def test_unsealed_token_unreadable_without_key_raises() -> None:
    box = make_box()
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    repository = PostgresFeedTokenRepository(database, secret_box=None)
    cursor.fetchone.side_effect = [
        {"id": 7},
        {
            "id": 21,
            "user_id": 7,
            "token_hint": "hint",
            "token_encrypted": sealed_str(box, "aigc_feed_plaintext"),
            "created_at": None,
            "last_used_at": None,
        },
    ]

    # 无密钥时绝不把密文当明文外发；由路由层映射 503
    with pytest.raises(FeedTokenSecretError):
        repository.get_or_create_feed_token(user_id=7, **_material(box))


def test_lookup_filters_revoked_and_disabled_and_throttles_last_use() -> None:
    repository, _, cursor = repository_with_cursor()
    expires_at = datetime(2027, 1, 1, tzinfo=timezone.utc)
    cursor.fetchone.return_value = {
        "token_id": 21,
        "user_id": 7,
        "created_at": None,
        "last_used_at": None,
        "email": "reader@example.com",
        "role": "user",
        "membership_tier": "member",
        "membership_expires_at": expires_at,
    }

    result = repository.get_user_by_feed_token_hash("a" * 64)

    lookup, update = cursor.execute.call_args_list
    assert "t.token_hash = %s" in lookup.args[0]
    assert "t.revoked_at IS NULL" in lookup.args[0]
    assert "u.disabled = FALSE" in lookup.args[0]
    # RSS 阅读器轮询频率远高于 MCP：1 小时节流窗口（MCP 为 5 分钟）
    assert "INTERVAL '1 hour'" in update.args[0]
    assert update.args[1] == (21,)
    assert result is not None
    assert result["membership_tier"] == "member"
    assert result["membership_expires_at"] == "2027-01-01T00:00:00Z"
    assert "token_hash" not in result


def test_lookup_unknown_hash_returns_none_without_touching_last_use() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchone.return_value = None

    assert repository.get_user_by_feed_token_hash("b" * 64) is None
    assert cursor.execute.call_count == 1


def test_feed_token_box_builds_from_configured_settings() -> None:
    """密钥装配契约：合法配置产出按版本密封的加密盒。"""
    key = WeChatSecretBox.generate_key_material()
    config = Settings(
        _env_file=None,
        feed_token_encryption_key=key,
        feed_token_encryption_key_version="v2",
    )

    box = build_feed_token_secret_box(config=config)

    assert box is not None
    assert box.seal("plain")["v"] == "v2"


def test_feed_token_box_returns_none_when_key_missing_or_invalid() -> None:
    missing = Settings(_env_file=None, feed_token_encryption_key="")
    assert build_feed_token_secret_box(config=missing) is None

    invalid = Settings(_env_file=None, feed_token_encryption_key="not-valid-base64!!!")
    assert build_feed_token_secret_box(config=invalid) is None


def test_feed_token_settings_reject_placeholder_and_bad_version() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="example placeholder"):
        Settings(_env_file=None, feed_token_encryption_key="CHANGEME123")
    with pytest.raises(ValidationError, match="key_version"):
        Settings(_env_file=None, feed_token_encryption_key_version="")
    with pytest.raises(ValidationError, match="key_version"):
        Settings(_env_file=None, feed_token_encryption_key_version="a" * 65)
