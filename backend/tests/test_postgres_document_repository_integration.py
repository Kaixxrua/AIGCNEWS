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
