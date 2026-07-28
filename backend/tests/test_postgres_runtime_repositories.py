from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

from backend.app.repositories.document_repository import DocumentRepository
from backend.app.repositories.postgres_document_repository import PostgresDocumentRepository
from backend.app.repositories.postgres_ingestion_task_repository import (
    PostgresIngestionTaskRepository,
)
from backend.app.repositories.postgres_rank_snapshot_repository import (
    PostgresRankSnapshotRepository,
)
from backend.app.repositories.rank_snapshot_repository import RankSnapshotRepository
from backend.app.repositories.task_repository import (
    IngestionTaskAdminRepository,
    IngestionTaskWriter,
    LatestTaskReader,
    MonitorTaskRepository,
    RecentTaskReader,
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


def test_postgres_adapters_expose_frozen_protocols() -> None:
    cursor = MagicMock()
    database = FakeDatabase(cursor)

    document: DocumentRepository = PostgresDocumentRepository(database)
    snapshot: RankSnapshotRepository = PostgresRankSnapshotRepository(database)
    tasks = PostgresIngestionTaskRepository(database)
    task_contracts: tuple[object, ...] = (
        tasks,
        tasks,
        tasks,
        tasks,
        tasks,
    )

    assert callable(document.search_document_page)
    assert callable(snapshot.upsert_rank_snapshot)
    for contract, method in zip(
        task_contracts,
        ("create_task", "get_latest_task", "get_recent_tasks", "list_tasks", "clear_all_tasks"),
    ):
        typed: IngestionTaskWriter | LatestTaskReader | RecentTaskReader | MonitorTaskRepository | IngestionTaskAdminRepository = contract  # type: ignore[assignment]
        assert callable(getattr(typed, method))


def test_document_upsert_normalizes_json_booleans_and_preserves_merge_rules() -> None:
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    repository = PostgresDocumentRepository(database)
    document = {
        "id": "doc-1",
        "source": "arxiv",
        "title": "Agent",
        "url": "https://example.test/doc-1",
        "summary": "summary",
        "published_date": "2026-07-28",
        "tags": ["AI", "Agent"],
        "indexed": 1,
    }

    repository.upsert_document(document)

    sql, params = cursor.execute.call_args.args
    assert "ON CONFLICT (id) DO UPDATE" in sql
    assert "documents.in_daily OR EXCLUDED.in_daily" in sql
    assert params["tags"] == '["AI", "Agent"]'
    assert params["indexed"] is True
    assert params["in_daily"] is False
    assert document["tags"] == '["AI", "Agent"]'
    assert database.transaction_count == 1


def test_document_search_uses_literal_ilike_filters_and_stable_pagination() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = {"cnt": 1}
    cursor.fetchall.return_value = [{"id": "doc-1"}]
    repository = PostgresDocumentRepository(FakeDatabase(cursor))

    result = repository.search_document_page(
        "50%_Agent", source=" ARXIV ", page=0, page_size=1000
    )

    assert result == {
        "items": [{"id": "doc-1"}],
        "total": 1,
        "page": 1,
        "page_size": 100,
    }
    count_call, rows_call = cursor.execute.call_args_list
    assert "ILIKE %s ESCAPE '='" in count_call.args[0]
    assert count_call.args[1][-1] == "arxiv"
    assert rows_call.args[1][-2:] == (100, 0)
    assert rows_call.args[1][0] == "%50=%=_Agent%"
    assert 'id COLLATE "C" ASC' in rows_call.args[0]


def test_task_insert_returns_identity_and_list_shape_matches_mysql() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = {"id": 7}
    database = FakeDatabase(cursor)
    repository = PostgresIngestionTaskRepository(database)

    assert repository.create_task("daily") == 7
    assert "RETURNING id" in cursor.execute.call_args.args[0]

    cursor.reset_mock()
    cursor.fetchone.return_value = {"cnt": 2}
    cursor.fetchall.return_value = [{"id": 2}, {"id": 1}]
    assert repository.list_tasks(page=2, page_size=1) == {
        "items": [{"id": 2}, {"id": 1}],
        "total": 2,
        "page": 2,
        "page_size": 1,
    }
    assert cursor.execute.call_args.args[1] == (1, 1)


def test_snapshot_upsert_and_score_sync_share_one_transaction() -> None:
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    repository = PostgresRankSnapshotRepository(database)

    repository.upsert_rank_snapshot("doc-1", "2026-07-28", "daily", 4, 3.0, 2.0)

    assert database.transaction_count == 1
    upsert_call, sync_call = cursor.execute.call_args_list
    assert "ON CONFLICT (doc_id, snapshot_date, source_channel)" in upsert_call.args[0]
    assert "LEAST(document_rank_snapshots.rank_in_period" in upsert_call.args[0]
    assert "WITH aggregate AS" in sync_call.args[0]
    assert sync_call.args[1] == ("doc-1", "2026-07-28", "doc-1", "2026-07-28")


def test_snapshot_period_filter_uses_postgres_array_parameter() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = [{"snapshot_date": "2026-07-28"}]
    repository = PostgresRankSnapshotRepository(FakeDatabase(cursor))

    dates = repository.get_snapshot_dates(source="github", period="daily")

    assert dates == ["2026-07-28"]
    sql, params = cursor.execute.call_args.args
    assert "s.source_channel = ANY(%s)" in sql
    assert params[0] == "github"
    assert params[1] == [
        "github_trending_daily",
        "github_hot_daily",
        "github_fallback",
    ]
