from __future__ import annotations

import inspect
import unittest
from typing import Any

from backend.app.domain.search_semantics import escape_like_literal
from backend.app.repositories.document_repository import (
    DocumentAdminWriter,
    DocumentFeedReader,
    DocumentRankingReader,
    DocumentRepository,
    DocumentRetrievalReader,
    DocumentSearchReader,
    DocumentStatisticsReader,
    DocumentWriter,
    DocumentXSnapshotBackfillReader,
)
from backend.app.repositories.postgres_document_repository import (
    _document_search_candidates,
)


def _without_annotations(function: Any) -> inspect.Signature:
    signature = inspect.signature(function)
    return signature.replace(
        parameters=[
            parameter.replace(annotation=inspect.Parameter.empty)
            for parameter in signature.parameters.values()
        ],
        return_annotation=inspect.Signature.empty,
    )


class DocumentRepositoryContractTests(unittest.TestCase):
    def test_combined_repository_preserves_narrow_capabilities(self) -> None:
        for capability in (
            DocumentWriter,
            DocumentSearchReader,
            DocumentRetrievalReader,
            DocumentRankingReader,
            DocumentFeedReader,
            DocumentStatisticsReader,
            DocumentAdminWriter,
        ):
            self.assertIn(capability, DocumentRepository.__mro__)

    def test_public_method_signatures_are_frozen(self) -> None:
        expected = {
            DocumentWriter.upsert_document: "(self, doc)",
            DocumentWriter.update_document_pdf_path: "(self, doc_id, local_pdf_path)",
            DocumentWriter.delete_document: "(self, doc_id)",
            DocumentWriter.delete_documents: "(self, doc_ids)",
            DocumentSearchReader.search_document_page: (
                "(self, query, *, source=None, page=1, page_size=20)"
            ),
            DocumentSearchReader.search_documents: (
                "(self, query, limit=20, *, source=None)"
            ),
            DocumentSearchReader.get_existing_document_summaries: (
                "(self, *, ids=None, urls=None, titles=None)"
            ),
            DocumentRetrievalReader.get_documents_by_ids: (
                "(self, document_ids, limit=5)"
            ),
            DocumentRetrievalReader.get_documents_by_title_tokens: (
                "(self, tokens, *, min_matches=3, limit=5)"
            ),
            DocumentRankingReader.get_today_ranked_documents: (
                "(self, limit=15, *, source=None)"
            ),
            DocumentRankingReader.get_knowledge_ranked_documents: (
                "(self, limit=50, *, source=None)"
            ),
            DocumentFeedReader.get_top_documents: "(self, limit=10, source_type=None)",
            DocumentFeedReader.get_recent_top_documents: (
                "(self, *, source_type, since_date, limit=10)"
            ),
            DocumentFeedReader.get_latest_documents: "(self, limit=10)",
            DocumentStatisticsReader.get_document_count: "(self)",
            DocumentStatisticsReader.get_source_counts: "(self)",
            DocumentStatisticsReader.get_today_document_count: "(self)",
            DocumentAdminWriter.clear_all_documents: "(self)",
            DocumentXSnapshotBackfillReader.list_x_snapshot_backfill_rows: "(self)",
        }
        for method, signature in expected.items():
            with self.subTest(method=method.__name__):
                self.assertEqual(str(_without_annotations(method)), signature)

    def test_search_candidate_relaxation_is_characterized(self) -> None:
        self.assertEqual(_document_search_candidates("Agent"), ["Agent"])
        candidates = _document_search_candidates("帮我找 AI Agent 学习资料")
        self.assertEqual(candidates[0], "帮我找 AI Agent 学习资料")
        self.assertIn("Agent", candidates)
        self.assertNotIn("AI", candidates[1:])

    def test_like_escape_treats_wildcards_and_escape_literal_as_text(self) -> None:
        self.assertEqual(escape_like_literal("50%_done=yes"), "50=%=_done==yes")


if __name__ == "__main__":
    unittest.main()
