from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Iterator

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
    from backend.app.repositories.postgres_ingestion_task_repository import (
        PostgresIngestionTaskRepository,
    )
    from backend.app.repositories.postgres_rank_snapshot_repository import (
        PostgresRankSnapshotRepository,
    )
finally:
    os.chdir(_IMPORT_CWD)


def _test_dsn() -> str:
    dsn = os.environ.get("TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is required for PostgreSQL integration tests")
    try:
        database = str(conninfo_to_dict(dsn).get("dbname") or "")
    except Exception as exc:
        pytest.skip(f"TEST_POSTGRES_DSN is not a valid PostgreSQL DSN: {exc}")
    if "test" not in database.lower():
        pytest.skip("TEST_POSTGRES_DSN dbname must contain 'test'")
    return dsn


@pytest.fixture(scope="module")
def repositories() -> Iterator[tuple[Any, Any, Any]]:
    dsn = _test_dsn()
    schema = f"runtime_it_{uuid.uuid4().hex}"
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
        yield (
            PostgresDocumentRepository(database),
            PostgresIngestionTaskRepository(database),
            PostgresRankSnapshotRepository(database),
        )
    finally:
        database.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _document(doc_id: str, **overrides: Any) -> dict[str, Any]:
    document = {
        "id": doc_id,
        "source": "arxiv",
        "source_channel": "huggingface_daily_html",
        "title": f"Agent paper {doc_id}",
        "url": f"https://example.test/{doc_id}",
        "summary": "Agent orchestration and RAG",
        "published_date": "2026-07-28",
        "tags": ["Agent", "RAG"],
        "score": 2.0,
        "raw_score": 3.0,
        "rank_in_period": 5,
        "indexed": 1,
        "in_daily": 1,
        "created_at": "2026-07-28T01:00:00+00:00",
    }
    document.update(overrides)
    return document


def test_real_postgres_document_upsert_search_feeds_and_stats(repositories) -> None:
    documents, _, _ = repositories
    documents.upsert_document(_document("doc-b", raw_score=4.0, rank_in_period=3))
    documents.upsert_document(_document("doc-a", raw_score=4.0, rank_in_period=2))
    documents.upsert_document(
        _document(
            "doc-a",
            published_date="",
            summary="Updated Agent summary",
            raw_score=1.0,
            rank_in_period=9,
            indexed=0,
            in_daily=0,
            in_weekly=1,
        )
    )

    detail = documents.get_paper_detail("doc-a")
    assert detail is not None
    assert detail["published_date"] == "2026-07-28"
    assert detail["raw_score"] == 4.0
    assert detail["rank_in_period"] == 2
    projected = {row["id"]: row for row in documents.get_latest_documents()}
    assert projected["doc-a"]["indexed"] is False
    assert projected["doc-a"]["in_daily"] is True
    assert projected["doc-a"]["in_weekly"] is True
    assert documents.search_document_page("agent", page=1, page_size=1) == {
        "items": [detail],
        "total": 2,
        "page": 1,
        "page_size": 1,
    }
    assert {row["id"] for row in documents.get_top_documents()} == {"doc-a", "doc-b"}
    assert documents.get_document_count() == 2
    assert documents.get_source_counts() == {"arxiv": 2}
    summaries = documents.get_existing_document_summaries(ids=["doc-a"], urls=["missing"])
    assert summaries["id:doc-a"] == "Updated Agent summary"
    assert documents.get_today_document_count() == 2


def test_real_postgres_tasks_preserve_order_pagination_and_clear(repositories) -> None:
    _, tasks, _ = repositories
    first = tasks.create_task("first")
    second = tasks.create_task("second")
    tasks.finish_task(first, status="failed", error_msg="boom", item_count=3)

    assert tasks.get_latest_task()["id"] == second
    assert [row["id"] for row in tasks.get_recent_tasks(2)] == [second, first]
    page = tasks.list_tasks(page=2, page_size=1)
    assert page["total"] == 2
    assert [row["id"] for row in page["items"]] == [first]
    assert page["items"][0]["error_msg"] == "boom"
    assert tasks.clear_all_tasks() == 2


def test_real_postgres_snapshots_sync_filter_order_and_delete(repositories) -> None:
    documents, _, snapshots = repositories
    documents.upsert_document(_document("github-one", source="github", rank_in_period=10))
    snapshots.upsert_rank_snapshot("doc-a", "2026-07-28", "huggingface_daily_html", 2, 3.0, 2.0)
    snapshots.upsert_rank_snapshot("doc-a", "2026-07-28", "huggingface_weekly_html", 1, 8.0, 7.0)
    snapshots.upsert_rank_snapshot("doc-a", "2026-07-28", "huggingface_daily_html", 5, 1.0, 1.0)
    snapshots.upsert_rank_snapshot("github-one", "2026-07-28", "github_trending_daily", 1, 4.0, 4.0)

    rows = snapshots.get_snapshot_documents("2026-07-28")
    assert [row["id"] for row in rows] == ["github-one", "doc-a", "doc-a"]
    arxiv_rows = [row for row in rows if row["id"] == "doc-a"]
    assert {(row["raw_score"], row["score"]) for row in arxiv_rows} == {(8.0, 7.0)}
    assert snapshots.get_snapshot_dates(source="arxiv", period="daily") == ["2026-07-28"]
    assert snapshots.get_snapshot_source_counts("2026-07-28") == {"arxiv": 1, "github": 1}
    assert snapshots.get_snapshot_doc_ids("2026-07-28", "huggingface_daily_html") == {"doc-a"}
    assert snapshots.delete_snapshots_by_channel("2026-07-28", "huggingface_weekly_html") == 1
