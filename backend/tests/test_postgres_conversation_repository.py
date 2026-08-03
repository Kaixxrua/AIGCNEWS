from __future__ import annotations

import inspect
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

from backend.app.repositories.conversation_repository import ConversationRepository
from backend.app.repositories.postgres_conversation_repository import (
    PostgresConversationRepository,
    _deserialize_message,
)


class Cursor:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, Any]] = []
        self.rowcount = 0

    def __enter__(self) -> Cursor:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.calls.append((sql, params))

    def fetchone(self) -> Any:
        return self.responses.pop(0)

    def fetchall(self) -> Any:
        return self.responses.pop(0)


class Database:
    def __init__(self, responses: list[Any]) -> None:
        self.cursor = Cursor(responses)
        self.connection = MagicMock()
        self.connection.cursor.return_value = self.cursor
        self.entered = 0
        self.exited = 0

    @contextmanager
    def transaction(self):
        self.entered += 1
        try:
            yield self.connection
        finally:
            self.exited += 1


def stripped(function: Any) -> inspect.Signature:
    signature = inspect.signature(function)
    return signature.replace(
        parameters=[
            parameter.replace(annotation=inspect.Parameter.empty)
            for parameter in signature.parameters.values()
        ],
        return_annotation=inspect.Signature.empty,
    )


def test_public_signatures_match_conversation_protocol() -> None:
    methods = (
        "get_owned_conversation_context",
        "list_conversations",
        "ensure_conversation",
        "create_conversation",
        "delete_owned_conversation",
        "get_owned_message_regeneration_preflight",
        "append_message_pair",
        "delete_owned_message_branch",
        "prepare_owned_regeneration",
        "count_user_messages_today",
        "cleanup_stale_conversations",
    )
    for name in methods:
        assert stripped(getattr(PostgresConversationRepository, name)) == stripped(
            getattr(ConversationRepository, name)
        )


def test_jsonb_and_legacy_json_text_normalize_to_mysql_message_shape() -> None:
    base = {"thinking": "reasoning", "status": "streaming"}

    native = _deserialize_message(
        {**base, "sources_json": [{"id": "doc"}], "attachments_json": None}
    )
    legacy = _deserialize_message(
        {**base, "sources_json": '[{"id": "doc"}]', "attachments_json": "invalid"}
    )

    for item in (native, legacy):
        assert item["sources"] == [{"id": "doc"}]
        assert item["attachments"] == []
        assert item["thinking_preview"] == "reasoning"
        assert item["has_thinking"] is True
        assert item["is_streaming"] is True


def test_append_pair_uses_returning_jsonb_and_one_transaction() -> None:
    conversation = {"id": 7, "user_id": 3, "title": "Question"}
    user_row = {
        "id": 11,
        "conversation_id": 7,
        "role": "user",
        "content": "Question",
        "thinking": "",
        "sources_json": [],
        "attachments_json": [],
        "status": "done",
    }
    assistant_row = {
        **user_row,
        "id": 12,
        "role": "assistant",
        "content": "Answer",
        "thinking": "Reasoning",
        "sources_json": [{"id": "doc"}],
    }
    database = Database(
        [
            conversation,
            user_row,
            assistant_row,
            {"cnt": 2},
            [{"id": 12}, {"id": 11}],
            {"cnt": 2},
            {"content": "Answer"},
            {"content": "Question"},
            [{"id": 7}],
            conversation,
            [user_row, assistant_row],
        ]
    )

    result = PostgresConversationRepository(database).append_message_pair(
        user_id=3,
        conversation_id=None,
        scope="global",
        scope_key=None,
        user_message="Question",
        assistant_content="Answer",
        assistant_thinking="Reasoning",
        sources=[{"id": "doc"}],
    )

    message_inserts = [
        call for call in database.cursor.calls if "INSERT INTO chat_messages" in call[0]
    ]
    assert len(message_inserts) == 2
    assert all("%s::jsonb" in sql and "RETURNING *" in sql for sql, _ in message_inserts)
    assert result["assistant_message"]["sources"] == [{"id": "doc"}]
    assert [message["id"] for message in result["messages"]] == [11, 12]
    assert database.entered == database.exited == 1


def test_regeneration_preflight_reads_owned_message_without_mutation() -> None:
    target = {
        "id": 11,
        "conversation_id": 7,
        "thinking": "",
        "sources_json": [],
        "attachments_json": [{"modality": "vision"}],
        "status": "done",
    }
    database = Database([target])

    result = PostgresConversationRepository(
        database
    ).get_owned_message_regeneration_preflight(user_id=3, message_id=11)

    sql, params = database.cursor.calls[0]
    assert "c.user_id = %s" in sql
    assert "DELETE" not in sql.upper() and "FOR UPDATE" not in sql.upper()
    assert params == (11, 3)
    assert result is not None and result["attachments"] == [{"modality": "vision"}]
    assert database.entered == database.exited == 1


def test_regeneration_locks_owned_target_before_ordered_suffix_delete() -> None:
    target = {
        "id": 11,
        "conversation_id": 7,
        "created_at": "2026-07-23T10:00:00+00:00",
        "content": "Question",
        "thinking": "",
        "sources_json": [],
        "attachments_json": [],
        "status": "done",
    }
    database = Database(
        [
            target,
            [{"id": 11}, {"id": 12}],
            {"cnt": 0},
            None,
            None,
            {"id": 7, "user_id": 3},
            [],
        ]
    )

    result = PostgresConversationRepository(database).prepare_owned_regeneration(
        user_id=3, message_id=11
    )

    first_sql, first_params = database.cursor.calls[0]
    suffix_sql, suffix_params = database.cursor.calls[1]
    assert "c.user_id = %s" in first_sql and "FOR UPDATE" in first_sql
    assert first_params == (11, 3)
    assert "created_at > %s" in suffix_sql and "id >= %s" in suffix_sql
    assert "ORDER BY created_at ASC, id ASC" in suffix_sql
    assert suffix_params[-1] == 11
    assert result is not None and result["deleted_ids"] == [11, 12]
    assert result["target_message"]["id"] == 11
    assert database.entered == database.exited == 1


def test_foreign_delete_is_non_mutating_and_cleanup_is_bounded() -> None:
    foreign = Database([None])
    assert not PostgresConversationRepository(foreign).delete_owned_conversation(
        user_id=3, conversation_id=9
    )
    assert len(foreign.cursor.calls) == 1
    assert "user_id = %s FOR UPDATE" in foreign.cursor.calls[0][0]

    cleanup = Database([[{"id": 1}, {"id": 2}]])
    cleanup.cursor.rowcount = 2
    assert (
        PostgresConversationRepository(cleanup).cleanup_stale_conversations(
            stale_days=7, limit=5
        )
        == 2
    )
    sql, params = cleanup.cursor.calls[0]
    assert "CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')" in sql
    assert "ORDER BY last_accessed_at ASC, updated_at ASC, id ASC" in sql
    assert "FOR UPDATE" in sql
    assert params == (7, 5)


def test_daily_count_uses_cst_calendar_inside_transaction() -> None:
    database = Database([{"cnt": 6}])

    assert PostgresConversationRepository(database).count_user_messages_today(3) == 6

    sql, params = database.cursor.calls[0]
    assert sql.count("AT TIME ZONE 'Asia/Shanghai'") == 2
    assert params == (3,)
    assert database.entered == database.exited == 1
