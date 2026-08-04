from __future__ import annotations

import hashlib
import unittest

from backend.app.services.ingestion.document_projection import (
    document_id,
    paper_identity_keys,
    project_documents,
    select_top_for_write,
    sort_papers_for_write,
)


class IngestionDocumentProjectionTests(unittest.TestCase):
    def test_document_id_preserves_precedence_hash_and_period_independence(self) -> None:
        arxiv = {
            "source": "arxiv",
            "arxiv_id": "2607.00001",
            "url": "https://ignored",
            "source_channel": "daily",
        }
        self.assertEqual(
            document_id(arxiv),
            hashlib.md5(b"arxiv:2607.00001").hexdigest(),
        )
        self.assertEqual(
            document_id({**arxiv, "source_channel": "monthly"}),
            document_id(arxiv),
        )
        self.assertEqual(
            document_id(
                {
                    "source": "github",
                    "full_name": "owner/repo",
                    "title": "ignored",
                }
            ),
            hashlib.md5(b"github:owner/repo").hexdigest(),
        )
        self.assertEqual(
            document_id({"source": "news", "url": "https://item", "title": "ignored"}),
            hashlib.md5(b"news:https://item").hexdigest(),
        )
        # x 源以 tweet_id 为稳定身份（URL 漂移不产生重复）
        self.assertEqual(
            document_id(
                {
                    "source": "x",
                    "tweet_id": "2083948654377996480",
                    "url": "https://ignored",
                }
            ),
            hashlib.md5(b"x:2083948654377996480").hexdigest(),
        )
        # 缺 tweet_id 时回退通用 url 分支
        self.assertEqual(
            document_id({"source": "x", "url": "https://x.com/a/status/1"}),
            hashlib.md5(b"x:https://x.com/a/status/1").hexdigest(),
        )

    def test_projection_preserves_content_precedence_metadata_and_defaults(self) -> None:
        documents = project_documents(
            [
                {
                    "source": "github",
                    "title": "Full",
                    "full_text": "full",
                    "abstract": "abstract",
                    "summary": "summary",
                    "stars": "12",
                    "score": "3.5",
                    "channel": "github_daily",
                    "in_daily": 1,
                },
                {"title": "Fallback", "stars": "invalid"},
            ]
        )

        self.assertEqual(documents[0].page_content, "full")
        self.assertEqual(documents[0].metadata["stars"], 12)
        self.assertEqual(documents[0].metadata["raw_score"], 3.5)
        self.assertEqual(documents[0].metadata["source_channel"], "github_daily")
        self.assertEqual(documents[0].metadata["in_daily"], 1)
        self.assertEqual(documents[1].page_content, "Fallback")
        self.assertEqual(documents[1].metadata["source"], "unknown")
        self.assertEqual(documents[1].metadata["stars"], 0)
        self.assertEqual(documents[1].metadata["in_weekly"], 0)

    def test_identity_keys_keep_id_url_title_order(self) -> None:
        paper = {
            "source": "news",
            "url": " https://item ",
            "title": " Item ",
        }
        self.assertEqual(
            paper_identity_keys(paper),
            [
                f"id:{document_id(paper)}",
                "url:https://item",
                "title:Item",
            ],
        )

    def test_write_sort_is_deterministic_without_mutating_input(self) -> None:
        papers = [
            {"source": "news", "channel": "b", "published_date": "2026-07-24", "title": "B"},
            {"source": "arxiv", "channel": "a", "published_date": "2026-07-24", "title": "A"},
        ]

        sorted_papers = sort_papers_for_write(papers)

        self.assertEqual([paper["title"] for paper in sorted_papers], ["A", "B"])
        self.assertEqual([paper["title"] for paper in papers], ["B", "A"])

    def test_top_selection_keeps_mutation_and_stable_write_order(self) -> None:
        papers = [
            {"source": "news", "title": "B", "score": 20},
            {"source": "arxiv", "title": "A", "raw_score": 30},
            {"source": "github", "title": "C", "score": 10},
        ]

        selected = select_top_for_write(papers, 2)

        self.assertEqual([paper["title"] for paper in papers], ["A", "B", "C"])
        self.assertEqual([paper["title"] for paper in selected], ["A", "B"])
        self.assertEqual(select_top_for_write([], 10), [])


if __name__ == "__main__":
    unittest.main()
