from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from backend.app.core.database import DatabaseLifecycle
from backend.app.repositories.mysql_document_repository import MySQLDocumentRepository


class MySQLDocumentRepositoryTests(unittest.TestCase):
    def test_upsert_normalizes_input_and_uses_transaction(self) -> None:
        repository, database, _, cursor = self._transaction_repository()
        document = {
            "id": "doc-1",
            "source": "github",
            "title": "Example",
            "url": "https://example.test",
            "summary": "Summary",
            "published_date": "2026-07-23",
            "tags": ["AI", "Agent"],
        }

        repository.upsert_document(document)

        self.assertEqual(document["tags"], json.dumps(["AI", "Agent"], ensure_ascii=False))
        self.assertEqual(document["rank_in_period"], 9999)
        self.assertEqual(document["raw_score"], 0.0)
        self.assertIn("created_at", document)
        sql, params = cursor.execute.call_args.args
        self.assertIn("score=GREATEST(score, VALUES(score))", sql)
        self.assertIn("rank_in_period=LEAST", sql)
        self.assertIs(params, document)
        database.transaction.assert_called_once_with()
        database.connection.assert_not_called()

    def test_pdf_path_update_uses_transaction(self) -> None:
        repository, database, _, cursor = self._transaction_repository()

        repository.update_document_pdf_path("doc-1", "/tmp/doc.pdf")

        cursor.execute.assert_called_once_with(
            "UPDATE documents SET local_pdf_path = %s WHERE id = %s",
            ("/tmp/doc.pdf", "doc-1"),
        )
        database.transaction.assert_called_once_with()

    def test_search_clamps_page_and_escapes_literal_query(self) -> None:
        repository, database, _, cursor = self._connection_repository()
        cursor.fetchone.return_value = {"cnt": 1}
        cursor.fetchall.return_value = [{"id": "doc-1"}]

        result = repository.search_document_page(
            "50%_done=yes",
            source=" GitHub ",
            page=0,
            page_size=1000,
        )

        self.assertEqual(result, {"items": [{"id": "doc-1"}], "total": 1, "page": 1, "page_size": 100})
        count_params = cursor.execute.call_args_list[0].args[1]
        self.assertEqual(count_params, ("%50=%=_done==yes%",) * 3 + ("github",))
        rows_params = cursor.execute.call_args_list[1].args[1]
        self.assertEqual(rows_params[-2:], (100, 0))
        database.connection.assert_called_once_with()
        database.transaction.assert_not_called()

    def test_empty_search_returns_without_database_access(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        repository = MySQLDocumentRepository(database)

        result = repository.search_document_page("  ", page=-1, page_size=0)

        self.assertEqual(result, {"items": [], "total": 0, "page": 1, "page_size": 1})
        database.connection.assert_not_called()

    def test_id_batch_preserves_caller_order_and_limit(self) -> None:
        repository, database, _, cursor = self._connection_repository()
        cursor.fetchall.return_value = [{"id": "second"}, {"id": "first"}]

        result = repository.get_documents_by_ids(["second", "first"], limit=4)

        sql, params = cursor.execute.call_args.args
        normalized = " ".join(sql.split())
        self.assertIn("WHERE id IN (%s, %s)", normalized)
        self.assertIn("ORDER BY FIELD(id, %s, %s) LIMIT %s", normalized)
        self.assertEqual(params, ("second", "first", "second", "first", 4))
        self.assertEqual(result, [{"id": "second"}, {"id": "first"}])
        database.connection.assert_called_once_with()

    def test_empty_id_batch_skips_database_access(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        repository = MySQLDocumentRepository(database)

        self.assertEqual(repository.get_documents_by_ids([]), [])
        database.connection.assert_not_called()

    def test_title_token_ranking_preserves_match_and_order_semantics(self) -> None:
        repository, _, _, cursor = self._connection_repository()
        cursor.fetchall.return_value = [{"id": "doc-1", "keyword_score": 3}]

        result = repository.get_documents_by_title_tokens(
            ["alpha", "beta", "gamma"], min_matches=3, limit=6
        )

        sql, params = cursor.execute.call_args.args
        normalized = " ".join(sql.split())
        self.assertEqual(normalized.count("(LOWER(title) LIKE %s)"), 3)
        self.assertIn("WHERE (LOWER(title) LIKE %s OR LOWER(title) LIKE %s", normalized)
        self.assertIn("HAVING keyword_score >= %s", normalized)
        self.assertIn(
            "ORDER BY keyword_score DESC, CASE WHEN source = 'arxiv' THEN 0 ELSE 1 END ASC, "
            "COALESCE(raw_score, score, 0) DESC, published_date DESC LIMIT %s",
            normalized,
        )
        self.assertEqual(
            params,
            ("%alpha%", "%beta%", "%gamma%") * 2 + (3, 6),
        )
        self.assertEqual(result, [{"id": "doc-1", "keyword_score": 3}])

    def test_title_token_ranking_preserves_current_wildcard_behavior(self) -> None:
        repository, _, _, cursor = self._connection_repository()
        cursor.fetchall.return_value = []

        repository.get_documents_by_title_tokens(["50%", "under_score", "agent"])

        self.assertEqual(cursor.execute.call_args.args[1][0:3], ("%50%%", "%under_score%", "%agent%"))

    def test_ranked_lists_preserve_raw_score_orders_and_source_filters(self) -> None:
        repository, _, _, cursor = self._connection_repository()
        cursor.fetchall.return_value = []

        repository.get_today_ranked_documents(5, source="github")
        today_sql, today_params = cursor.execute.call_args.args
        repository.get_knowledge_ranked_documents(7, source="news")
        knowledge_sql, knowledge_params = cursor.execute.call_args.args

        self.assertIn("LEFT(created_at, 10) = %s AND source = %s", today_sql)
        self.assertIn("ORDER BY raw_score DESC, rank_in_period ASC LIMIT %s", today_sql)
        self.assertRegex(today_params[0], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(today_params[1:], ("github", 5))
        self.assertIn("WHERE source = %s", knowledge_sql)
        self.assertIn("ORDER BY raw_score DESC, created_at DESC LIMIT %s", knowledge_sql)
        self.assertEqual(knowledge_params, ("news", 7))

    def test_summary_lookup_preserves_placeholder_and_result_keys(self) -> None:
        repository, _, connection, cursor = self._connection_repository()
        cursor.fetchall.return_value = [
            {
                "id": "doc-1",
                "url": "https://example.test",
                "title": "Example",
                "summary": " summary ",
            }
        ]

        result = repository.get_existing_document_summaries(
            ids=[" doc-1 "],
            urls=["https://example.test"],
            titles=["Example"],
        )

        sql, params = cursor.execute.call_args.args
        self.assertIn("id IN (%s)", sql)
        self.assertIn("url IN (%s)", sql)
        self.assertIn("title IN (%s)", sql)
        self.assertEqual(params, ("doc-1", "https://example.test", "Example"))
        self.assertEqual(
            result,
            {
                "id:doc-1": "summary",
                "url:https://example.test": "summary",
                "title:Example": "summary",
            },
        )
        connection.commit.assert_called_once_with()

    def test_papers_today_query_preserves_fallback_order_and_commits(self) -> None:
        repository, _, connection, cursor = self._connection_repository()
        cursor.fetchall.side_effect = [[], [{"id": "fallback"}]]

        result = repository.get_today_top_arxiv_documents()

        self.assertEqual(result, [{"id": "fallback"}])
        today_sql, today_params = cursor.execute.call_args_list[0].args
        fallback_call = cursor.execute.call_args_list[1]
        self.assertIn("LEFT(created_at, 10) = %s", today_sql)
        self.assertIn("ORDER BY COALESCE(raw_score, score, 0) DESC", today_sql)
        self.assertRegex(today_params[0], r"^\d{4}-\d{2}-\d{2}$")
        self.assertIn("ORDER BY created_at DESC, COALESCE(raw_score, score, 0) DESC", fallback_call.args[0])
        self.assertEqual(connection.commit.call_count, 2)

    def test_papers_detail_and_pdf_queries_preserve_projection_and_commit(self) -> None:
        repository, _, connection, cursor = self._connection_repository()
        cursor.fetchone.side_effect = [
            {"id": "paper-1", "source": "arxiv"},
            {"local_pdf_path": None, "url": "https://arxiv.org/abs/2603.12255", "source": "arxiv"},
        ]

        detail = repository.get_paper_detail("paper-1")
        pdf_source = repository.get_paper_pdf_source("paper-1")

        self.assertEqual(detail["id"], "paper-1")
        self.assertEqual(pdf_source["source"], "arxiv")
        detail_sql, detail_params = cursor.execute.call_args_list[0].args
        pdf_sql, pdf_params = cursor.execute.call_args_list[1].args
        self.assertIn("published_date, tags, score, raw_score", detail_sql)
        self.assertIn("WHERE id = %s", detail_sql)
        self.assertEqual(detail_params, ("paper-1",))
        self.assertEqual(
            pdf_sql,
            "SELECT local_pdf_path, url, source FROM documents WHERE id = %s LIMIT 1",
        )
        self.assertEqual(pdf_params, ("paper-1",))
        self.assertEqual(connection.commit.call_count, 2)

    def test_top_and_latest_share_github_metric_projection(self) -> None:
        repository, _, _, cursor = self._connection_repository()
        cursor.fetchall.return_value = []

        repository.get_top_documents(5, "github")
        top_sql = cursor.execute.call_args.args[0]
        repository.get_latest_documents(7)
        latest_sql = cursor.execute.call_args.args[0]

        projection = "COALESCE(NULLIF(d.stars, 0), NULLIF(gs.stars, 0), c.stars, 0) AS stars"
        self.assertIn(projection, top_sql)
        self.assertIn(projection, latest_sql)
        self.assertIn("WHERE d.source = %s", top_sql)
        self.assertIn("ORDER BY d.created_at DESC", latest_sql)

    def test_clear_counts_and_deletes_in_one_transaction(self) -> None:
        repository, database, _, cursor = self._transaction_repository()
        cursor.fetchone.return_value = {"cnt": 4}

        result = repository.clear_all_documents()

        self.assertEqual(result, 4)
        self.assertEqual(len(cursor.execute.call_args_list), 2)
        self.assertIn("COUNT(*)", cursor.execute.call_args_list[0].args[0])
        self.assertEqual(cursor.execute.call_args_list[1].args[0], "DELETE FROM documents")
        database.transaction.assert_called_once_with()
        database.connection.assert_not_called()

    @staticmethod
    def _transaction_repository():
        database = MagicMock(spec=DatabaseLifecycle)
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        database.transaction.return_value.__enter__.return_value = connection
        return MySQLDocumentRepository(database), database, connection, cursor

    @staticmethod
    def _connection_repository():
        database = MagicMock(spec=DatabaseLifecycle)
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        database.connection.return_value.__enter__.return_value = connection
        return MySQLDocumentRepository(database), database, connection, cursor


if __name__ == "__main__":
    unittest.main()
