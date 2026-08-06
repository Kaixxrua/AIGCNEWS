from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from psycopg import errors

from backend.app.domain.wechat_secret_box import WeChatSecretBox
from backend.app.repositories.postgres_wechat_account_repository import (
    PostgresWeChatOfficialAccountRepository,
    WeChatOfficialAccountConflictError,
)
from backend.app.repositories.postgres_wechat_article_repository import (
    PostgresWeChatArticleRepository,
    WeChatArticleConflictError,
)
from backend.app.repositories.postgres_wechat_follow_repository import (
    PostgresWeChatFollowRepository,
    WeChatFollowAccountNotFoundError,
)
from backend.app.repositories.postgres_wechat_session_repository import (
    PostgresWeChatSessionRepository,
)
from backend.app.repositories.wechat_account_repository import (
    WeChatOfficialAccountRepository,
)
from backend.app.repositories.wechat_article_repository import WeChatArticleRepository
from backend.app.repositories.wechat_follow_repository import WeChatFollowRepository
from backend.app.repositories.wechat_session_repository import (
    WeChatLoginAttemptRepository,
    WeChatSessionRepository,
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


def _secret_box() -> WeChatSecretBox:
    return WeChatSecretBox.generate_for_test()


def _session_repo(cursor: MagicMock) -> PostgresWeChatSessionRepository:
    return PostgresWeChatSessionRepository(FakeDatabase(cursor), _secret_box())


def _account_repo(cursor: MagicMock) -> PostgresWeChatOfficialAccountRepository:
    return PostgresWeChatOfficialAccountRepository(FakeDatabase(cursor))


def _article_repo(cursor: MagicMock) -> PostgresWeChatArticleRepository:
    return PostgresWeChatArticleRepository(FakeDatabase(cursor))


def test_session_adapter_conforms_to_protocols() -> None:
    repo = PostgresWeChatSessionRepository(FakeDatabase(MagicMock()), _secret_box())
    login_contract: WeChatLoginAttemptRepository = repo
    session_contract: WeChatSessionRepository = repo
    assert callable(login_contract.create_login_attempt)
    assert callable(session_contract.get_wechat_session)


def test_account_adapter_conforms_to_protocol() -> None:
    repo = PostgresWeChatOfficialAccountRepository(FakeDatabase(MagicMock()))
    contract: WeChatOfficialAccountRepository = repo
    assert callable(contract.upsert_wechat_account)


def test_article_adapter_conforms_to_protocol() -> None:
    repo = PostgresWeChatArticleRepository(FakeDatabase(MagicMock()))
    contract: WeChatArticleRepository = repo
    assert callable(contract.upsert_wechat_articles)
    assert callable(contract.get_wechat_article)


def test_create_login_attempt_encrypts_uuid_cookie() -> None:
    cursor = MagicMock()
    repo = _session_repo(cursor)
    box = repo._secret_box
    envelope = box.seal("uuid=abc123")
    cursor.fetchone.return_value = {
        "attempt_id": str(uuid4()),
        "owner_id": 1,
        "encrypted_uuid_cookie": envelope["ct"],
        "encrypted_uuid_cookie_nonce": envelope["nonce"],
        "encryption_key_version": "v1",
        "status": "waiting_scan",
        "upstream_status": 0,
        "expires_at": datetime.now(timezone.utc),
        "error_code": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    attempt_id = uuid4()
    expires = datetime.now(timezone.utc)

    result = repo.create_login_attempt(
        1,
        attempt_id,
        {"uuid_cookie": "uuid=abc123", "expires_at": expires},
    )

    insert = cursor.execute.call_args_list[0]
    assert "wechat_login_attempts" in insert.args[0]
    assert insert.args[1][2] != "uuid=abc123"  # encrypted
    assert insert.args[1][4] == "v1"  # key version
    assert result.get("uuid_cookie") == "uuid=abc123"


def test_get_login_attempt_decrypts_and_returns_uuid_cookie() -> None:
    cursor = MagicMock()
    repo = _session_repo(cursor)
    box = repo._secret_box
    envelope = box.seal("uuid=secret")
    cursor.fetchone.return_value = {
        "attempt_id": str(uuid4()),
        "owner_id": 1,
        "encrypted_uuid_cookie": envelope["ct"],
        "encrypted_uuid_cookie_nonce": envelope["nonce"],
        "encryption_key_version": "v1",
        "status": "waiting_scan",
        "upstream_status": 0,
        "expires_at": datetime.now(timezone.utc),
        "error_code": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    result = repo.get_login_attempt(1, uuid4())

    assert result is not None
    assert result["uuid_cookie"] == "uuid=secret"


def test_get_login_attempt_returns_none_on_bad_key() -> None:
    cursor = MagicMock()
    repo = _session_repo(cursor)
    cursor.fetchone.return_value = {
        "encrypted_uuid_cookie": "bad",
        "encrypted_uuid_cookie_nonce": "bad",
        "encryption_key_version": "v1",
    }

    assert repo.get_login_attempt(1, uuid4()) is None


def test_save_session_encrypts_token_and_cookie() -> None:
    cursor = MagicMock()
    repo = _session_repo(cursor)
    cursor.fetchone.return_value = {
        "id": 1,
        "owner_id": 1,
        "encrypted_token": "ct",
        "encrypted_token_nonce": "nonce",
        "encrypted_cookie": "ct",
        "encrypted_cookie_nonce": "nonce",
        "encryption_key_version": "v1",
        "status": "active",
        "account_name": "Test",
        "account_avatar_url": "",
        "last_validated_at": None,
        "last_used_at": None,
        "expires_at": None,
        "invalid_reason_code": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    repo.save_wechat_session(
        1,
        {
            "token": "token123",
            "cookie": "cookie=value",
            "account_name": "Test",
        },
    )

    upsert = cursor.execute.call_args_list[0]
    assert "ON CONFLICT (owner_id)" in upsert.args[0]
    assert upsert.args[1][1] != "token123"
    assert upsert.args[1][3] != "cookie=value"


def test_account_upsert_requires_fakeid() -> None:
    cursor = MagicMock()
    repo = _account_repo(cursor)
    with pytest.raises(ValueError, match="fakeid"):
        repo.upsert_wechat_account(1, {"nickname": "Test"})


def test_account_upsert_maps_unique_violation() -> None:
    cursor = MagicMock()
    repo = _account_repo(cursor)

    class FakeUniqueViolation(errors.UniqueViolation):
        @property
        def diag(self):
            return MagicMock(constraint_name="uq_wechat_official_accounts_owner_fakeid")

    cursor.execute.side_effect = FakeUniqueViolation("duplicate")

    with pytest.raises(WeChatOfficialAccountConflictError):
        repo.upsert_wechat_account(1, {"fakeid": "fake1", "nickname": "Test"})


def test_article_upsert_serializes_raw_metadata() -> None:
    cursor = MagicMock()
    repo = _article_repo(cursor)
    cursor.rowcount = 2

    count = repo.upsert_wechat_articles(
        1,
        42,
        [
            {
                "stable_article_key": "1001-1",
                "message_id": "1001",
                "itemidx": 1,
                "title": "T1",
                "digest": "D1",
                "author": "A1",
                "article_url": "https://x",
                "cover_url": "",
                "source_url": "",
                "published_at": None,
                "raw_metadata": {"key": "value"},
            },
            {
                "stable_article_key": "1001-2",
                "message_id": "1001",
                "itemidx": 2,
                "title": "T2",
                "raw_metadata": {},
            },
        ],
    )

    assert count == 2
    call = cursor.executemany.call_args
    # Tuple order: ..., published_at, raw_metadata, content_html, content_fetched_at
    assert json.loads(call.args[1][0][-3]) == {"key": "value"}
    assert call.args[1][0][-2] == ""  # metadata-only payloads carry no body
    assert call.args[1][0][-1] is None
    assert "ON CONFLICT (account_id, stable_article_key)" in call.args[0]


def test_article_upsert_content_never_clobbered_by_empty() -> None:
    cursor = MagicMock()
    repo = _article_repo(cursor)
    cursor.rowcount = 1

    repo.upsert_wechat_articles(
        1,
        42,
        [
            {
                "stable_article_key": "1001-1",
                "title": "T1",
                "content_html": "<p>正文</p>",
                "content_fetched_at": "2026-08-06T07:44:00+00:00",
            }
        ],
    )

    call = cursor.executemany.call_args
    assert call.args[1][0][-2] == "<p>正文</p>"
    assert call.args[1][0][-1] == "2026-08-06T07:44:00+00:00"
    # Empty incoming bodies must not erase a stored body (MP-admin path
    # syncs metadata only).
    assert "WHEN EXCLUDED.content_html <> '' THEN EXCLUDED.content_html" in call.args[0]
    assert "ELSE wechat_articles.content_html" in call.args[0]


def test_get_wechat_article_returns_row_with_content() -> None:
    cursor = MagicMock()
    repo = _article_repo(cursor)
    cursor.fetchone.return_value = {
        "id": 11,
        "account_id": 42,
        "content_html": "<p>正文</p>",
        "has_content": True,
    }

    article = repo.get_wechat_article(1, 42, 11)

    assert article is not None
    assert article["content_html"] == "<p>正文</p>"
    sql = cursor.execute.call_args.args[0]
    assert "content_html" in sql and "content_fetched_at" in sql
    assert cursor.execute.call_args.args[1] == (42, 11)


def test_get_wechat_article_returns_none_when_missing() -> None:
    cursor = MagicMock()
    repo = _article_repo(cursor)
    cursor.fetchone.return_value = None

    assert repo.get_wechat_article(1, 42, 999) is None


def test_article_upsert_empty_list_returns_zero() -> None:
    cursor = MagicMock()
    repo = _article_repo(cursor)
    assert repo.upsert_wechat_articles(1, 42, []) == 0
    cursor.executemany.assert_not_called()


def test_article_upsert_maps_unique_violation() -> None:
    cursor = MagicMock()
    repo = _article_repo(cursor)

    class FakeUniqueViolation(errors.UniqueViolation):
        @property
        def diag(self):
            return MagicMock(constraint_name="uq_wechat_articles_account_stable_key")

    cursor.executemany.side_effect = FakeUniqueViolation("duplicate")

    with pytest.raises(WeChatArticleConflictError):
        repo.upsert_wechat_articles(
            1,
            42,
            [{"stable_article_key": "k", "itemidx": 1, "raw_metadata": {}}],
        )


# ----------------------------------------------------------------------
# Follow repository (platform catalog + per-user follows)
# ----------------------------------------------------------------------


def _follow_repo(cursor: MagicMock) -> PostgresWeChatFollowRepository:
    return PostgresWeChatFollowRepository(FakeDatabase(cursor))


def _catalog_row(**overrides):
    row = {
        "id": 7,
        "owner_id": 1,
        "fakeid": "MzIxxx",
        "nickname": "AI 迷思录",
        "alias": "aimisi",
        "avatar_url": "https://avatar",
        "signature": "sig",
        "enabled": True,
        "sort_order": 0,
        "last_sync_status": "never",
        "last_sync_message": "",
        "last_sync_at": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    row.update(overrides)
    return row


def test_follow_adapter_conforms_to_protocol() -> None:
    repo = PostgresWeChatFollowRepository(FakeDatabase(MagicMock()))
    contract: WeChatFollowRepository = repo
    assert callable(contract.follow_account)
    assert callable(contract.list_catalog_with_follow_state)


def test_catalog_lists_enabled_accounts_with_follow_state() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {**_catalog_row(id=7), "follow_user_id": 3},
        {**_catalog_row(id=8), "follow_user_id": None},
    ]
    repo = _follow_repo(cursor)

    items = repo.list_catalog_with_follow_state(3)

    call = cursor.execute.call_args
    assert "LEFT JOIN wechat_account_follows" in call.args[0]
    assert "WHERE a.enabled" in call.args[0]
    assert call.args[1] == (3,)
    assert [item["followed"] for item in items] == [True, False]
    assert "follow_user_id" not in items[0]


def test_get_enabled_catalog_account_filters_disabled() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    repo = _follow_repo(cursor)

    assert repo.get_enabled_catalog_account(7) is None
    call = cursor.execute.call_args
    assert "WHERE a.enabled AND a.id = %s" in call.args[0]


def test_follow_account_inserts_idempotently() -> None:
    cursor = MagicMock()
    cursor.rowcount = 0  # ON CONFLICT DO NOTHING hit an existing row
    repo = _follow_repo(cursor)

    assert repo.follow_account(3, 7) is False
    call = cursor.execute.call_args
    assert "ON CONFLICT (user_id, account_id) DO NOTHING" in call.args[0]
    assert call.args[1] == (3, 7)


def test_follow_account_maps_foreign_key_violation_to_not_found() -> None:
    cursor = MagicMock()
    repo = _follow_repo(cursor)

    class FakeFkViolation(errors.ForeignKeyViolation):
        pass

    cursor.execute.side_effect = FakeFkViolation("missing account")

    with pytest.raises(WeChatFollowAccountNotFoundError):
        repo.follow_account(3, 999)


def test_unfollow_account_returns_whether_row_removed() -> None:
    cursor = MagicMock()
    cursor.rowcount = 1
    repo = _follow_repo(cursor)

    assert repo.unfollow_account(3, 7) is True
    call = cursor.execute.call_args
    assert "DELETE FROM wechat_account_follows" in call.args[0]
    assert call.args[1] == (3, 7)


def test_list_followed_account_ids_only_returns_enabled() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = [{"account_id": 7}, {"account_id": 9}]
    repo = _follow_repo(cursor)

    assert repo.list_followed_account_ids(3) == [7, 9]
    call = cursor.execute.call_args
    assert "JOIN wechat_official_accounts a ON a.id = f.account_id" in call.args[0]
    assert "a.enabled" in call.args[0]


def test_list_recent_articles_for_accounts_empty_input() -> None:
    cursor = MagicMock()
    repo = _article_repo(cursor)
    assert repo.list_recent_articles_for_accounts([], per_account=5) == {}
    cursor.execute.assert_not_called()


def test_list_recent_articles_for_accounts_groups_rows_per_account() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {"id": 1, "account_id": 7, "title": "A", "stable_article_key": "k1"},
        {"id": 2, "account_id": 7, "title": "B", "stable_article_key": "k2"},
        {"id": 3, "account_id": 9, "title": "C", "stable_article_key": "k3"},
    ]
    repo = _article_repo(cursor)

    grouped = repo.list_recent_articles_for_accounts([7, 9, 7, 11], per_account=3)

    call = cursor.execute.call_args
    assert "CROSS JOIN LATERAL" in call.args[0]
    assert call.args[1] == ([7, 9, 11], 3)  # deduped input
    assert [a["title"] for a in grouped[7]] == ["A", "B"]
    assert [a["title"] for a in grouped[9]] == ["C"]
    assert grouped[11] == []
