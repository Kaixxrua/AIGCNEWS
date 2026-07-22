from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.services.indexing.github_project_semantic_indexer import (
    GitHubProjectSemanticIndexer,
    build_project_semantic_chunks,
    project_semantic_fingerprint,
)


PROJECT = {
    "repo_id": "owner/repo",
    "full_name": "owner/repo",
    "title": "owner/repo",
    "description": "Frontend development toolkit",
    "description_zh": "前端开发工具",
    "category_slug": "coding_tools",
    "category_name": "编程工具",
    "subcategory_slug": "frameworks",
    "subcategory_name": "框架",
    "tags_json": '["前端"]',
    "topics_json": '["frontend"]',
    "language": "TypeScript",
    "pushed_at": "2026-07-22",
}


class GitHubProjectSemanticIndexerTests(unittest.TestCase):
    def test_profile_exists_without_readme(self) -> None:
        chunks = build_project_semantic_chunks(PROJECT, "")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0][0], "profile")
        self.assertIn("Frontend development toolkit", chunks[0][2])
        self.assertIn("前端开发工具", chunks[0][2])

    def test_metrics_do_not_change_fingerprint(self) -> None:
        first = project_semantic_fingerprint(PROJECT, "abc")
        changed = {**PROJECT, "stars": 100_000, "forks": 3_000}
        self.assertEqual(first, project_semantic_fingerprint(changed, "abc"))

    def test_sync_project_upserts_stable_chunks_and_status(self) -> None:
        db = MagicMock()
        vectors = MagicMock()
        vectors.upsert_project_chunks.return_value = 1
        embeddings = MagicMock()
        embeddings.embed_documents.return_value = [[0.1] * 1024]
        indexer = GitHubProjectSemanticIndexer(db=db, vectors=vectors, embeddings=embeddings)

        result = indexer.sync_project(PROJECT, fetch_readme=False)

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(db.upsert_github_project_semantic_source.call_count, 2)
        vector_chunk = vectors.upsert_project_chunks.call_args.args[1][0]
        self.assertEqual(vector_chunk.repo_id, "owner/repo")
        self.assertEqual(len(vector_chunk.chunk_id), 64)
        self.assertEqual(vector_chunk.chunk_kind, "profile")

    def test_index_failure_is_recorded_without_raising(self) -> None:
        db = MagicMock()
        vectors = MagicMock()
        vectors.upsert_project_chunks.side_effect = RuntimeError("milvus unavailable")
        embeddings = MagicMock()
        embeddings.embed_documents.return_value = [[0.1] * 1024]
        indexer = GitHubProjectSemanticIndexer(db=db, vectors=vectors, embeddings=embeddings)

        result = indexer.sync_project(PROJECT, fetch_readme=False)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(db.upsert_github_project_semantic_source.call_args.args[0]["index_status"], "failed")


if __name__ == "__main__":
    unittest.main()
