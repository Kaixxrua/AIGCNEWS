from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.core.database import DatabaseLifecycle
from backend.app.repositories.mysql_rank_snapshot_repository import MySQLRankSnapshotRepository


class MySQLRankSnapshotRepositoryTests(unittest.TestCase):
    def test_upsert_and_score_synchronization_share_transaction(self) -> None:
        repository, database, _, cursor = self._transaction_repository()

        repository.upsert_rank_snapshot(
            "doc-1",
            "2026-07-23",
            "github_trending_daily",
            2,
            12.5,
            8.5,
        )

        self.assertEqual(len(cursor.execute.call_args_list), 2)
        upsert_sql, upsert_params = cursor.execute.call_args_list[0].args
        sync_sql, sync_params = cursor.execute.call_args_list[1].args
        self.assertIn("rank_in_period=LEAST", upsert_sql)
        self.assertIn("raw_score=GREATEST", upsert_sql)
        self.assertEqual(upsert_params[:6], ("doc-1", "2026-07-23", "github_trending_daily", 2, 12.5, 8.5))
        self.assertIn("MAX(raw_score)", sync_sql)
        self.assertEqual(sync_params, ("doc-1", "2026-07-23", "doc-1", "2026-07-23"))
        database.transaction.assert_called_once_with()
        database.connection.assert_not_called()

    def test_snapshot_documents_preserve_filters_projection_and_order(self) -> None:
        repository, database, _, cursor = self._connection_repository()
        cursor.fetchall.return_value = [{"id": "doc-1"}]

        result = repository.get_snapshot_documents(
            "2026-07-23",
            source_channel="github_trending_daily",
            source_type="github",
            limit=25,
        )

        self.assertEqual(result, [{"id": "doc-1"}])
        sql, params = cursor.execute.call_args.args
        self.assertIn("s.source_channel = %s", sql)
        self.assertIn("d.source = %s", sql)
        self.assertIn("COALESCE(NULLIF(d.stars, 0)", sql)
        self.assertIn("CASE WHEN d.source = 'github' THEN s.rank_in_period ELSE 9999 END ASC", sql)
        self.assertIn("CASE WHEN d.source != 'github' THEN -s.raw_score ELSE 0 END ASC", sql)
        self.assertEqual(params, ("2026-07-23", "github_trending_daily", "github", 25))
        database.connection.assert_called_once_with()

    def test_all_source_type_does_not_add_source_filter(self) -> None:
        repository, _, _, cursor = self._connection_repository()
        cursor.fetchall.return_value = []

        repository.get_snapshot_documents("2026-07-23", source_type="all")

        sql, params = cursor.execute.call_args.args
        self.assertNotIn("d.source = %s", sql)
        self.assertEqual(params, ("2026-07-23", 500))

    def test_snapshot_dates_expand_period_channels_and_preserve_order(self) -> None:
        repository, _, _, cursor = self._connection_repository()
        cursor.fetchall.return_value = [{"snapshot_date": "2026-07-23"}]

        result = repository.get_snapshot_dates(2, source="arxiv", period="daily")

        self.assertEqual(result, ["2026-07-23"])
        sql, params = cursor.execute.call_args.args
        self.assertIn("s.source_channel IN (%s)", sql)
        self.assertIn("ORDER BY s.snapshot_date DESC", sql)
        self.assertEqual(params, ("arxiv", "huggingface_daily_html", 2))

    def test_unknown_period_returns_without_database_access(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        repository = MySQLRankSnapshotRepository(database)

        self.assertEqual(repository.get_snapshot_dates(source="news", period="weekly"), [])
        database.connection.assert_not_called()
        database.transaction.assert_not_called()

    def test_source_counts_and_doc_ids_preserve_result_shapes(self) -> None:
        repository, _, _, cursor = self._connection_repository()
        cursor.fetchall.side_effect = [
            [{"source": "github", "cnt": 3}],
            [{"doc_id": "doc-1"}, {"doc_id": "doc-2"}],
        ]

        counts = repository.get_snapshot_source_counts("2026-07-23")
        doc_ids = repository.get_snapshot_doc_ids(
            "2026-07-23",
            "github_trending_daily",
        )

        self.assertEqual(counts, {"github": 3})
        self.assertEqual(doc_ids, {"doc-1", "doc-2"})
        doc_id_sql, doc_id_params = cursor.execute.call_args_list[1].args
        self.assertIn("s.source_channel = %s", doc_id_sql)
        self.assertEqual(doc_id_params, ("2026-07-23", "github_trending_daily"))

    def test_delete_returns_rowcount_and_uses_transaction(self) -> None:
        repository, database, _, cursor = self._transaction_repository()
        cursor.rowcount = 4

        result = repository.delete_snapshots_by_channel(
            "2026-07-23",
            "github_trending_daily",
        )

        self.assertEqual(result, 4)
        cursor.execute.assert_called_once_with(
            """
            DELETE FROM document_rank_snapshots
            WHERE snapshot_date = %s AND source_channel = %s
        """,
            ("2026-07-23", "github_trending_daily"),
        )
        database.transaction.assert_called_once_with()
        database.connection.assert_not_called()

    @staticmethod
    def _transaction_repository():
        database = MagicMock(spec=DatabaseLifecycle)
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        database.transaction.return_value.__enter__.return_value = connection
        return MySQLRankSnapshotRepository(database), database, connection, cursor

    @staticmethod
    def _connection_repository():
        database = MagicMock(spec=DatabaseLifecycle)
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        database.connection.return_value.__enter__.return_value = connection
        return MySQLRankSnapshotRepository(database), database, connection, cursor


if __name__ == "__main__":
    unittest.main()
