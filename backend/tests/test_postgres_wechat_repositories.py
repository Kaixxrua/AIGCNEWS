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
from backend.app.repositories.postgres_wechat_session_repository import (
    PostgresWeChatSessionRepository,
)
from backend.app.repositories.wechat_account_repository import (
    WeChatOfficialAccountRepository,
)
from backend.app.repositories.wechat_article_repository import WeChatArticleRepository
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
    assert json.loads(call.args[1][0][-1]) == {"key": "value"}
    assert "ON CONFLICT (account_id, stable_article_key)" in call.args[0]


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
