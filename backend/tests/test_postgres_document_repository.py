from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

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


def test_deserialize_row_link_card_json_and_bad_json() -> None:
    row = {"id": "x:lc", "link_card": '{"url": "https://youtu.be/x", "title": "t"}'}
    result = _deserialize_row_media(row)
    assert result["link_card"] == {"url": "https://youtu.be/x", "title": "t"}
    bad = _deserialize_row_media({"id": "x:lc2", "link_card": "not-json"})
    assert bad["link_card"] is None


def test_upsert_document_persists_link_card() -> None:
    repository, _, cursor = repository_with_cursor()

    repository.upsert_document(
        {
            "id": "x:2006",
            "source": "x",
            "source_channel": "x_daily_watchlist",
            "title": "tweet",
            "url": "https://x.com/minimax_ai/status/2086",
            "link_card": {
                "url": "https://www.youtube.com/watch?v=S9O3FPumX4Q",
                "title": "MiniMax H3",
                "description": "open-weight video model",
                "domain": "youtube.com",
                "image_url": "https://pbs.twimg.com/card_img/x.jpg",
                "image_width": 1280,
                "image_height": 720,
                "card_type": "player",
            },
        }
    )

    sql = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "link_card" in sql
    # 冲突更新走 COALESCE(NULLIF(...))：新值缺失时保留已有链接卡片
    assert "link_card=COALESCE(NULLIF(EXCLUDED.link_card, ''), documents.link_card)" in sql
    assert json.loads(params["link_card"])["card_type"] == "player"


def test_upsert_document_link_card_defaults_to_none() -> None:
    repository, _, cursor = repository_with_cursor()

    repository.upsert_document(
        {
            "id": "x:2007",
            "source": "x",
            "title": "tweet",
            "url": "https://x.com/openai/status/2007",
        }
    )

    params = cursor.execute.call_args.args[1]
    assert params["link_card"] is None


def test_upsert_document_persists_retweeted_by() -> None:
    repository, _, cursor = repository_with_cursor()

    repository.upsert_document(
        {
            "id": "x:2008",
            "source": "x",
            "source_channel": "x_daily_watchlist",
            "title": "tweet",
            "url": "https://x.com/originalauthor/status/2008",
            "retweeted_by": "watchlist_account",
        }
    )

    sql = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "retweeted_by" in sql
    # 冲突更新走 COALESCE(NULLIF(...))：新一轮无转贴者信息时保留已有标注
    assert "retweeted_by=COALESCE(NULLIF(EXCLUDED.retweeted_by, ''), documents.retweeted_by)" in sql
    assert params["retweeted_by"] == "watchlist_account"

    repository.upsert_document(
        {"id": "x:2009", "source": "x", "title": "tweet", "url": "https://x.com/a/status/2009"}
    )
    assert cursor.execute.call_args.args[1]["retweeted_by"] is None



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
                "tweet_id": "2000",
                "language": "en",
                "text": "quoted text",
                "media": [],
                "published_at": "2026-08-07T01:00:00+00:00",
            },
        }
    )

    sql = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "quote" in sql
    # 冲突更新按 quote 的 tweet_id/text 合并，避免丢失已完成的引用译文。
    assert "quote=CASE" in sql
    assert "pg_input_is_valid(EXCLUDED.quote, 'jsonb')" in sql
    assert "jsonb_set(" in sql
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


def test_delete_documents_removes_documents_and_snapshots_in_one_transaction() -> None:
    repository, database, cursor = repository_with_cursor()
    cursor.fetchall.return_value = [{"id": "x:1001"}, {"id": "x:1002"}]

    deleted = repository.delete_documents(["x:1001", "x:1002", "x:missing"])

    assert deleted == ["x:1001", "x:1002"]
    assert database.transaction_count == 1
    calls = cursor.execute.call_args_list
    assert len(calls) == 2
    snapshots_sql, snapshots_params = calls[0].args
    assert "DELETE FROM document_rank_snapshots" in snapshots_sql
    assert "ANY(%s)" in snapshots_sql
    assert snapshots_params == (["x:1001", "x:1002", "x:missing"],)
    documents_sql, documents_params = calls[1].args
    assert "DELETE FROM documents" in documents_sql
    assert "RETURNING id" in documents_sql
    assert documents_params == (["x:1001", "x:1002", "x:missing"],)


def test_delete_documents_dedupes_ids_preserving_request_order() -> None:
    repository, database, cursor = repository_with_cursor()
    cursor.fetchall.return_value = [{"id": "x:2"}, {"id": "x:1"}]

    deleted = repository.delete_documents(["x:2", "x:1", "x:2"])

    assert deleted == ["x:2", "x:1"]
    assert database.transaction_count == 1
    _, documents_params = cursor.execute.call_args_list[1].args
    assert documents_params == (["x:2", "x:1"],)


def test_delete_documents_empty_list_opens_no_transaction() -> None:
    repository, database, cursor = repository_with_cursor()

    assert repository.delete_documents([]) == []
    assert database.transaction_count == 0
    cursor.execute.assert_not_called()


def test_delete_documents_failure_propagates_out_of_one_transaction() -> None:
    repository, database, cursor = repository_with_cursor()
    cursor.execute.side_effect = [None, RuntimeError("delete failed")]

    with pytest.raises(RuntimeError, match="delete failed"):
        repository.delete_documents(["x:1001", "x:1002"])

    # 只开启了一个事务：排行快照删除随 documents 删除失败一起回滚
    assert database.transaction_count == 1


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


def test_list_x_documents_for_probe_queries_x_documents_newest_first() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchall.return_value = [
        {"id": "x:2", "url": "https://x.com/a/status/2", "quote": None},
    ]

    rows = repository.list_x_documents_for_probe(150)

    sql = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "d.source = 'x'" in sql
    assert "ORDER BY d.published_at DESC" in sql
    assert "d.quote" in sql
    assert params == (150,)
    assert rows == [
        {"id": "x:2", "url": "https://x.com/a/status/2", "quote": None},
    ]


def test_list_x_documents_for_probe_clamps_limit() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchall.return_value = []

    repository.list_x_documents_for_probe(99999)
    assert cursor.execute.call_args.args[1] == (5000,)

    repository.list_x_documents_for_probe(0)
    assert cursor.execute.call_args.args[1] == (1,)


def test_list_x_documents_for_probe_deserializes_quote_json() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchall.return_value = [
        {
            "id": "x:3",
            "url": "https://x.com/a/status/3",
            "quote": '{"url": "https://x.com/b/status/9", "text": "quoted"}',
        },
        {"id": "x:4", "url": "https://x.com/a/status/4", "quote": "{bad json"},
    ]

    rows = repository.list_x_documents_for_probe(10)

    assert rows[0]["quote"] == {"url": "https://x.com/b/status/9", "text": "quoted"}
    assert rows[1]["quote"] is None


def test_clear_quotes_for_docs_updates_in_one_transaction() -> None:
    repository, database, cursor = repository_with_cursor()
    cursor.fetchall.return_value = [{"id": "x:1"}, {"id": "x:2"}]

    cleared = repository.clear_quotes_for_docs(["x:1", "x:2", "x:9"])

    assert database.transaction_count == 1
    sql = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "UPDATE documents SET quote = NULL" in sql
    assert "id = ANY(%s)" in sql
    assert "quote IS NOT NULL" in sql
    assert "RETURNING id" in sql
    assert params == (["x:1", "x:2", "x:9"],)
    # 以 RETURNING 为准区分已清理与无卡/未找到
    assert cleared == ["x:1", "x:2"]


def test_clear_quotes_for_docs_dedupes_ids_and_skips_empty() -> None:
    repository, database, cursor = repository_with_cursor()
    cursor.fetchall.return_value = [{"id": "x:1"}]

    cleared = repository.clear_quotes_for_docs(["x:1", "x:1"])

    assert cursor.execute.call_args.args[1] == (["x:1"],)
    assert cleared == ["x:1"]

    cursor.reset_mock()
    before = database.transaction_count
    assert repository.clear_quotes_for_docs([]) == []
    cursor.execute.assert_not_called()
    assert database.transaction_count == before


def test_list_arxiv_document_summaries_pages_by_id_and_clamps_limit() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchall.return_value = [{"id": "b", "arxiv_id": "2609.00002", "summary": "text"}]

    rows = repository.list_arxiv_document_summaries(after_id="a", limit=99999)

    sql = cursor.execute.call_args.args[0]
    assert "source = 'arxiv'" in sql
    assert "id > %s ORDER BY id LIMIT %s" in sql
    assert cursor.execute.call_args.args[1] == ("a", 10000)
    assert rows == [{"id": "b", "arxiv_id": "2609.00002", "summary": "text"}]

    repository.list_arxiv_document_summaries(limit=0)
    assert cursor.execute.call_args.args[1] == ("", 1)


@pytest.mark.parametrize(("rowcount", "expected"), [(1, True), (0, False)])
def test_update_document_summary_if_unchanged_is_conditional_and_null_safe(
    rowcount: int, expected: bool
) -> None:
    repository, database, cursor = repository_with_cursor()
    cursor.rowcount = rowcount

    assert repository.update_document_summary_if_unchanged("doc-1", None, "fresh") is expected

    assert database.transaction_count == 1
    sql = cursor.execute.call_args.args[0]
    assert "UPDATE documents SET summary = %s" in sql
    # 库中为 NULL 时 "summary = NULL" 永不命中，须用 IS NOT DISTINCT FROM 比对读出值
    assert "summary IS NOT DISTINCT FROM %s" in sql
    assert cursor.execute.call_args.args[1] == ("fresh", "doc-1", None)
