from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import MagicMock

from backend.app.repositories.postgres_document_repository import (
    PostgresDocumentRepository,
    _deserialize_row_media,
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


def repository_with_cursor():
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    return PostgresDocumentRepository(database), database, cursor


def test_upsert_document_serializes_media_and_tags() -> None:
    repository, _, cursor = repository_with_cursor()

    repository.upsert_document(
        {
            "id": "x:1001",
            "source": "x",
            "source_channel": "x_daily_watchlist",
            "title": "tweet",
            "url": "https://x.com/openai/status/1001",
            "summary": "summary",
            "tags": ["x", "daily", "openai"],
            "media": [
                {"type": "photo", "url": "https://pbs.twimg.com/a.jpg", "width": 100, "height": 100}
            ],
        }
    )

    assert cursor.execute.called
    sql = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "media" in sql
    assert params["media"] == '[{"type": "photo", "url": "https://pbs.twimg.com/a.jpg", "width": 100, "height": 100}]'
    assert params["tags"] == '["x", "daily", "openai"]'


def test_upsert_document_allows_null_media() -> None:
    repository, _, cursor = repository_with_cursor()

    repository.upsert_document(
        {
            "id": "x:1002",
            "source": "x",
            "title": "plain",
            "url": "https://x.com/openai/status/1002",
        }
    )

    params = cursor.execute.call_args.args[1]
    assert params["media"] is None


def test_fetch_rows_deserialize_media_json() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchall.return_value = [
        {
            "id": "x:1001",
            "media": '[{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]',
        }
    ]

    rows = repository._fetch_rows("SELECT id, media FROM documents", ())

    assert rows == [
        {
            "id": "x:1001",
            "media": [{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}],
        }
    ]


def test_fetch_one_deserialize_media_json() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchone.return_value = {
        "id": "x:1001",
        "media": '[{"type": "video", "url": "https://video.twimg.com/a.mp4"}]',
    }

    row = repository._fetch_one("SELECT id, media FROM documents WHERE id = %s", ("x:1001",))

    assert row == {
        "id": "x:1001",
        "media": [{"type": "video", "url": "https://video.twimg.com/a.mp4"}],
    }


def test_deserialize_row_media_bad_json_returns_none() -> None:
    row = {"id": "x:bad", "media": "not-json"}
    result = _deserialize_row_media(row)
    assert result["media"] is None


def test_deserialize_row_quote_json_and_bad_json() -> None:
    row = {"id": "x:q", "quote": '{"url": "https://x.com/a/status/1", "text": "hi"}'}
    result = _deserialize_row_media(row)
    assert result["quote"] == {"url": "https://x.com/a/status/1", "text": "hi"}
    bad = _deserialize_row_media({"id": "x:q2", "quote": "not-json"})
    assert bad["quote"] is None


def test_upsert_document_persists_quote() -> None:
    repository, _, cursor = repository_with_cursor()

    repository.upsert_document(
        {
            "id": "x:2004",
            "source": "x",
            "source_channel": "x_daily_watchlist",
            "title": "tweet",
            "url": "https://x.com/openai/status/2004",
            "quote": {
                "url": "https://x.com/comfyui/status/2000",
                "author": "comfyui",
                "author_name": "ComfyUI",
                "text": "quoted text",
                "media": [],
                "published_at": "2026-08-07T01:00:00+00:00",
            },
        }
    )

    sql = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "quote" in sql
    # 冲突更新走 COALESCE(NULLIF(...))：新值缺失时保留已有引用卡片
    assert "quote=COALESCE(NULLIF(EXCLUDED.quote, ''), documents.quote)" in sql
    assert json.loads(params["quote"])["author"] == "comfyui"


def test_upsert_document_quote_defaults_to_none() -> None:
    repository, _, cursor = repository_with_cursor()

    repository.upsert_document(
        {
            "id": "x:2005",
            "source": "x",
            "title": "tweet",
            "url": "https://x.com/openai/status/2005",
        }
    )

    params = cursor.execute.call_args.args[1]
    assert params["quote"] is None


def test_deserialize_row_media_missing_key_untouched() -> None:
    row = {"id": "x:nomedia"}
    result = _deserialize_row_media(row)
    assert "media" not in result


def test_delete_document_removes_document_and_snapshots() -> None:
    repository, _, cursor = repository_with_cursor()

    deleted = repository.delete_document("x:1001")

    assert deleted is True
    assert cursor.execute.called
    calls = [call.args[0] for call in cursor.execute.call_args_list]
    assert any("DELETE FROM document_rank_snapshots" in sql for sql in calls)
    assert any("DELETE FROM documents" in sql for sql in calls)


def test_delete_document_returns_false_when_missing() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 0

    deleted = repository.delete_document("x:missing")

    assert deleted is False


def test_upsert_document_persists_translation_zh() -> None:
    repository, _, cursor = repository_with_cursor()

    repository.upsert_document(
        {
            "id": "x:2001",
            "source": "x",
            "source_channel": "x_daily_watchlist",
            "title": "tweet",
            "url": "https://x.com/openai/status/2001",
            "summary": "original english text",
            "translation_zh": "中文译文",
        }
    )

    sql = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "translation_zh" in sql
    # 冲突更新走 COALESCE(NULLIF(...))：新值缺失时保留已有译文
    assert "translation_zh=COALESCE(NULLIF(EXCLUDED.translation_zh, ''), documents.translation_zh)" in sql
    assert params["translation_zh"] == "中文译文"


def test_upsert_document_translation_zh_defaults_to_none() -> None:
    repository, _, cursor = repository_with_cursor()

    repository.upsert_document(
        {
            "id": "x:2002",
            "source": "x",
            "title": "tweet",
            "url": "https://x.com/openai/status/2002",
        }
    )

    params = cursor.execute.call_args.args[1]
    assert params["translation_zh"] is None


def test_upsert_document_persists_author_name() -> None:
    repository, _, cursor = repository_with_cursor()

    repository.upsert_document(
        {
            "id": "x:2003",
            "source": "x",
            "source_channel": "x_daily_watchlist",
            "title": "tweet",
            "url": "https://x.com/openai/status/2003",
            "summary": "original english text",
            "author_name": "OpenAI",
        }
    )

    sql = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "author_name" in sql
    # 冲突更新走 COALESCE(NULLIF(...))：新值缺失时保留已有昵称
    assert "author_name=COALESCE(NULLIF(EXCLUDED.author_name, ''), documents.author_name)" in sql
    assert params["author_name"] == "OpenAI"


def test_upsert_document_author_name_defaults_to_none() -> None:
    repository, _, cursor = repository_with_cursor()

    repository.upsert_document(
        {
            "id": "x:2004",
            "source": "x",
            "title": "tweet",
            "url": "https://x.com/openai/status/2004",
        }
    )

    params = cursor.execute.call_args.args[1]
    assert params["author_name"] is None


def test_list_x_snapshot_backfill_rows_queries_x_documents() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchall.return_value = [
        {"id": "x:1", "published_at": "2026-08-07T01:00:00+00:00", "raw_score": 9.0, "score": 0.0},
    ]

    rows = repository.list_x_snapshot_backfill_rows()

    sql = cursor.execute.call_args.args[0]
    assert "d.source = 'x'" in sql
    # 不做有效性过滤：脏时间串留给服务层剔除并计数（管理端回报口径）
    assert "~" not in sql
    assert rows == [
        {"id": "x:1", "published_at": "2026-08-07T01:00:00+00:00", "raw_score": 9.0, "score": 0.0},
    ]
