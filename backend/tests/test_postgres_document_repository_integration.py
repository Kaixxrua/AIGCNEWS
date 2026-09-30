from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from backend.tests.postgres_test_safety import postgres_test_sandbox

_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")

    from backend.app.repositories.postgres_document_repository import (
        PostgresDocumentRepository,
    )
finally:
    os.chdir(_IMPORT_CWD)


@pytest.fixture(scope="module")
def postgres_documents() -> Iterator[tuple[Any, Any]]:
    with postgres_test_sandbox() as sandbox:
        database = sandbox.database
        yield PostgresDocumentRepository(database), database


def _insert_document(repository: Any, doc_id: str) -> None:
    repository.upsert_document(
        {
            "id": doc_id,
            "source": "x",
            "title": f"tweet {doc_id}",
            "url": f"https://x.com/openai/status/{doc_id}",
            "summary": "summary",
            "published_date": "2026-08-07",
            "tags": [],
        }
    )


def test_public_x_watchlist_keeps_quiet_accounts_and_uses_latest_real_nickname(
    postgres_documents: tuple[Any, Any],
) -> None:
    from backend.app.repositories.postgres_x_watch_repository import PostgresXWatchAccountRepository

    documents, database = postgres_documents
    accounts = PostgresXWatchAccountRepository(database)
    created = []
    try:
        for handle, enabled in (("thsottiaux", True), ("quiet", True), ("disabled", False)):
            created.append(accounts.create_x_watch_account({"screen_name": handle, "display_name": handle, "enabled": enabled}))
        for doc_id, handle, nickname, published in (
            ("it:x-name-old", "thsottiaux", "Old Name", "2020-01-01T00:00:00Z"),
            ("it:x-name-new", "thsottiaux", "Tibo", "2020-01-02T00:00:00Z"),
            ("it:x-name-rt", "other", "Other Author", "2020-01-03T00:00:00Z"),
        ):
            documents.upsert_document({
                "id": doc_id, "source": "x", "title": "test", "url": f"https://x.com/{handle}/status/1",
                "author_name": nickname, "published_at": published,
                "summary": "test", "published_date": published[:10], "tags": [],
                "retweeted_by": "thsottiaux" if handle == "other" else None,
            })
        labels = {row["screen_name"]: row["display_name"] for row in accounts.list_public_x_watch_accounts()}
        assert labels["thsottiaux"] == "Tibo"
        assert "quiet" in labels
        assert "disabled" not in labels
    finally:
        for account in created:
            accounts.delete_x_watch_account(account["id"])
        with database.transaction() as connection:
            connection.execute("DELETE FROM documents WHERE id IN ('it:x-name-old', 'it:x-name-new', 'it:x-name-rt')")


def _insert_rank_snapshot(database: Any, doc_id: str) -> None:
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO document_rank_snapshots
                (doc_id, snapshot_date, source_channel, rank_in_period,
                 raw_score, score, created_at)
            VALUES (%s, '2026-08-07', 'x_daily_watchlist', 1, 9.0, 9.0, 'now')
            """,
            (doc_id,),
        )


def test_upsert_round_trips_authors_and_arxiv_id_with_conflict_merge(
    postgres_documents: tuple[Any, Any],
) -> None:
    repository, _ = postgres_documents
    base_doc = {
        "id": "it:arxiv-authors",
        "source": "arxiv",
        "title": "paper",
        "url": "https://arxiv.org/abs/2403.12345",
        "summary": "summary",
        "published_date": "2026-08-07",
        "tags": [],
        "authors": ["Alice Zhang", "Bob Li"],
        "arxiv_id": "2403.12345",
    }
    repository.upsert_document(dict(base_doc))

    detail = repository.get_paper_detail("it:arxiv-authors")
    assert detail is not None
    assert detail["authors"] == '["Alice Zhang", "Bob Li"]'
    assert detail["arxiv_id"] == "2403.12345"
    found = repository.search_document_page("paper", source="arxiv")["items"]
    assert [row["arxiv_id"] for row in found] == ["2403.12345"]
    assert found[0]["authors"] == '["Alice Zhang", "Bob Li"]'

    # 冲突合并：不带作者的重爬保留旧值
    repository.upsert_document({k: v for k, v in base_doc.items() if k not in ("authors", "arxiv_id")})
    detail = repository.get_paper_detail("it:arxiv-authors")
    assert detail["authors"] == '["Alice Zhang", "Bob Li"]'
    assert detail["arxiv_id"] == "2403.12345"

    # 冲突合并：带新作者的回填/重爬覆盖旧值
    repository.upsert_document({**base_doc, "authors": ["Carol Wang"]})
    detail = repository.get_paper_detail("it:arxiv-authors")
    assert detail["authors"] == '["Carol Wang"]'


def test_upsert_x_document_returning_distinguishes_insert_from_conflict_update(
    postgres_documents: tuple[Any, Any],
) -> None:
    """xmax=0 探测在真实 PG 上区分 INSERT 与 ON CONFLICT UPDATE：新行 True、
    重复 upsert False；翻译辅助表写入不计入新行口径（仪表盘缓存失效契约）。"""
    repository, _ = postgres_documents
    doc = {
        "id": "it:x-inserted",
        "source": "x",
        "title": "tweet one",
        "url": "https://x.com/openai/status/it-x-inserted",
        "summary": "first",
        "published_date": "2026-08-07",
        "tags": [],
    }
    targets = [
        {
            "source_text": "hello world",
            "source_tweet_id": "it:x-inserted",
            "target_kind": "outer",
            "source_lang": "en",
        }
    ]

    assert repository.upsert_x_document_with_translation_targets(dict(doc), list(targets)) is True
    # 重复 upsert（带内容更新）→ False；翻译辅助表再次写入不影响该标记
    assert repository.upsert_x_document_with_translation_targets({**doc, "summary": "second"}, list(targets)) is False
    # 内容不变的纯重复 upsert 也走 ON CONFLICT UPDATE 分支 → False
    assert repository.upsert_x_document_with_translation_targets(dict(doc), []) is False


def test_delete_documents_removes_rows_and_snapshots_in_one_pass(
    postgres_documents: tuple[Any, Any],
) -> None:
    repository, database = postgres_documents
    for doc_id in ("it:bulk-1", "it:bulk-2", "it:bulk-3"):
        _insert_document(repository, doc_id)
        _insert_rank_snapshot(database, doc_id)

    deleted = repository.delete_documents(["it:bulk-1", "it:bulk-2", "it:missing"])

    assert deleted == ["it:bulk-1", "it:bulk-2"]
    with database.transaction() as connection:
        remaining_docs = connection.execute("SELECT id FROM documents WHERE id LIKE 'it:bulk-%' ORDER BY id").fetchall()
        remaining_snapshots = connection.execute(
            "SELECT doc_id FROM document_rank_snapshots WHERE doc_id LIKE 'it:bulk-%'"
        ).fetchall()
    assert [row["id"] for row in remaining_docs] == ["it:bulk-3"]
    assert [row["doc_id"] for row in remaining_snapshots] == ["it:bulk-3"]


def test_delete_documents_failure_rolls_back_rank_snapshot_deletes(
    postgres_documents: tuple[Any, Any],
) -> None:
    repository, database = postgres_documents
    _insert_document(repository, "it:keep")
    _insert_document(repository, "it:boom")
    _insert_rank_snapshot(database, "it:keep")
    _insert_rank_snapshot(database, "it:boom")
    with database.transaction() as connection:
        connection.execute(
            """
            CREATE FUNCTION abort_delete_boom() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'simulated mid-batch failure';
            END;
            $$
            """
        )
        connection.execute(
            """
            CREATE TRIGGER fail_delete_boom BEFORE DELETE ON documents
            FOR EACH ROW WHEN (OLD.id = 'it:boom') EXECUTE FUNCTION abort_delete_boom()
            """
        )
    try:
        with pytest.raises(Exception):
            repository.delete_documents(["it:keep", "it:boom"])

        with database.transaction() as connection:
            docs = connection.execute(
                "SELECT id FROM documents WHERE id IN ('it:keep', 'it:boom') ORDER BY id"
            ).fetchall()
            snapshots = connection.execute(
                "SELECT doc_id FROM document_rank_snapshots WHERE doc_id IN ('it:keep', 'it:boom') ORDER BY doc_id"
            ).fetchall()
        # documents 删除失败 → 同事务的 rank_snapshots 删除一并回滚，不留半完成状态
        assert [row["id"] for row in docs] == ["it:boom", "it:keep"]
        assert [row["doc_id"] for row in snapshots] == ["it:boom", "it:keep"]
    finally:
        with database.transaction() as connection:
            connection.execute("DROP TRIGGER IF EXISTS fail_delete_boom ON documents")
            connection.execute("DROP FUNCTION IF EXISTS abort_delete_boom")


def test_question_search_applies_date_window_and_recency_order(
    postgres_documents: tuple[Any, Any],
) -> None:
    from unittest.mock import patch

    from backend.app.repositories import postgres_document_repository as module

    repository, _ = postgres_documents
    rows = (
        ("it:intent-devday", "x", "Full recap of the DevDay announcements", "OpenAI launched GPT-6.1", "2026-09-29", 10.0),
        ("it:intent-codex", "x", "OpenAI Codex release notes", "rust-v0.159.2", "2026-09-30", 1.0),
        ("it:intent-old", "x", "OpenAI old headline", "old", "2026-08-01", 99.0),
        ("it:intent-paper", "arxiv", "An unrelated paper", "no match", "2026-09-30T05:49:02", 50.0),
    )
    ids = [row[0] for row in rows]
    try:
        for doc_id, source, title, summary, published, score in rows:
            repository.upsert_document(
                {
                    "id": doc_id,
                    "source": source,
                    "title": title,
                    "url": f"https://example.test/{doc_id}",
                    "summary": summary,
                    "published_date": published,
                    "tags": [],
                    "score": score,
                }
            )
        with patch.object(module, "_local_today", return_value="2026-09-30"):
            question = repository.search_document_page("简洁总结昨晚openai发布了什么", source="x")
            today = repository.search_document_page("今天有什么新闻")

        # 旧的高分帖被窗口挡掉；窗口内同层级按日期倒序。
        assert [row["id"] for row in question["items"]] == ["it:intent-codex", "it:intent-devday"]
        assert question["total"] == 2
        # 纯时间查询：只按日期过滤；arXiv 的 T 时刻不压过同日其他源，同日按热度。
        found = [row["id"] for row in today["items"] if row["id"] in ids]
        assert found == ["it:intent-paper", "it:intent-codex", "it:intent-devday"]
    finally:
        repository.delete_documents(ids)
