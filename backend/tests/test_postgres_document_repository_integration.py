from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from psycopg_pool import ConnectionPool

    from backend.app.core.postgres_database import PostgresDatabaseLifecycle
    from backend.app.core.postgres_migrations import PostgresMigrationRunner
    from backend.app.repositories.postgres_document_repository import (
        PostgresDocumentRepository,
    )
finally:
    os.chdir(_IMPORT_CWD)


def _test_dsn() -> str:
    dsn = os.environ.get("TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is required for PostgreSQL integration tests")
    database = str(conninfo_to_dict(dsn).get("dbname") or "")
    if "test" not in database.lower():
        pytest.skip("TEST_POSTGRES_DSN dbname must contain 'test'")
    return dsn


@pytest.fixture(scope="module")
def postgres_documents() -> Iterator[tuple[Any, Any]]:
    dsn = _test_dsn()
    schema = f"documents_it_{uuid.uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')
    scoped_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
    database = PostgresDatabaseLifecycle(
        lambda: ConnectionPool(
            conninfo=scoped_dsn,
            min_size=1,
            max_size=4,
            timeout=10,
            kwargs={"autocommit": False, "row_factory": psycopg.rows.dict_row},
            open=False,
        )
    )
    try:
        PostgresMigrationRunner(database).apply()
        yield PostgresDocumentRepository(database), database
    finally:
        database.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


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

    assert (
        repository.upsert_x_document_with_translation_targets(dict(doc), list(targets))
        is True
    )
    # 重复 upsert（带内容更新）→ False；翻译辅助表再次写入不影响该标记
    assert (
        repository.upsert_x_document_with_translation_targets(
            {**doc, "summary": "second"}, list(targets)
        )
        is False
    )
    # 内容不变的纯重复 upsert 也走 ON CONFLICT UPDATE 分支 → False
    assert (
        repository.upsert_x_document_with_translation_targets(dict(doc), [])
        is False
    )


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
        remaining_docs = connection.execute(
            "SELECT id FROM documents WHERE id LIKE 'it:bulk-%' ORDER BY id"
        ).fetchall()
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
                "SELECT doc_id FROM document_rank_snapshots "
                "WHERE doc_id IN ('it:keep', 'it:boom') ORDER BY doc_id"
            ).fetchall()
        # documents 删除失败 → 同事务的 rank_snapshots 删除一并回滚，不留半完成状态
        assert [row["id"] for row in docs] == ["it:boom", "it:keep"]
        assert [row["doc_id"] for row in snapshots] == ["it:boom", "it:keep"]
    finally:
        with database.transaction() as connection:
            connection.execute("DROP TRIGGER IF EXISTS fail_delete_boom ON documents")
            connection.execute("DROP FUNCTION IF EXISTS abort_delete_boom")
