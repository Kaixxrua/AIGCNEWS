from __future__ import annotations

import threading
import time
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

    def test_normalized_topics_and_tags_are_embedded_and_fingerprinted(self) -> None:
        normalized = {
            **PROJECT,
            "topics": ["frontend", "developer-tools"],
            "tags": ["前端", "开发工具"],
        }
        normalized.pop("topics_json")
        normalized.pop("tags_json")

        chunks = build_project_semantic_chunks(normalized, "")
        changed = {**normalized, "topics": ["frontend", "design-system"]}

        self.assertIn("Tags: 前端, 开发工具", chunks[0][2])
        self.assertIn("Topics: frontend, developer-tools", chunks[0][2])
        self.assertNotEqual(
            project_semantic_fingerprint(normalized, "abc"),
            project_semantic_fingerprint(changed, "abc"),
        )

    def test_sync_project_uses_one_repo_id_for_vector_and_status(self) -> None:
        canonical = {**PROJECT, "repo_id": "owner/canonical"}
        db = MagicMock()
        vectors = MagicMock()
        vectors.upsert_project_chunks.return_value = 1
        embeddings = MagicMock()
        embeddings.embed_documents.return_value = [[0.1] * 1024]
        indexer = GitHubProjectSemanticIndexer(db=db, vectors=vectors, embeddings=embeddings)

        result = indexer.sync_project(canonical, fetch_readme=False)

        self.assertEqual(result["repo_id"], "owner/canonical")
        self.assertEqual(vectors.upsert_project_chunks.call_args.args[0], "owner/canonical")
        self.assertEqual(vectors.upsert_project_chunks.call_args.args[1][0].repo_id, "owner/canonical")
        self.assertTrue(
            all(
                call.args[0]["repo_id"] == "owner/canonical"
                for call in db.upsert_github_project_semantic_source.call_args_list
            )
        )

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

    def test_sync_batch_runs_requested_concurrency_and_keeps_cursor_order(self) -> None:
        projects = [{**PROJECT, "repo_id": f"owner/repo-{index}"} for index in range(12)]
        db = MagicMock()
        db.list_github_projects_for_semantic_sync.return_value = projects
        embeddings = MagicMock()
        indexer = GitHubProjectSemanticIndexer(db=db, embeddings=embeddings)
        active = 0
        max_active = 0
        lock = threading.Lock()

        def sync_project(project, **_kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return {"repo_id": project["repo_id"], "status": "succeeded", "chunk_count": 1}

        indexer.sync_project = MagicMock(side_effect=sync_project)
        result = indexer.sync_batch(limit=12, concurrency=20, fetch_readme=False)

        self.assertGreater(max_active, 1)
        self.assertLessEqual(max_active, 20)
        self.assertEqual(result["counts"], {"succeeded": 12})
        self.assertEqual(result["last_repo_id"], "owner/repo-11")

    def test_sync_batch_isolates_unexpected_worker_failure(self) -> None:
        projects = [{**PROJECT, "repo_id": "owner/ok"}, {**PROJECT, "repo_id": "owner/bad"}]
        db = MagicMock()
        db.list_github_projects_for_semantic_sync.return_value = projects
        embeddings = MagicMock()
        indexer = GitHubProjectSemanticIndexer(db=db, embeddings=embeddings)

        def sync_project(project, **_kwargs):
            if project["repo_id"] == "owner/bad":
                raise RuntimeError("unexpected")
            return {"repo_id": project["repo_id"], "status": "succeeded", "chunk_count": 1}

        indexer.sync_project = MagicMock(side_effect=sync_project)
        result = indexer.sync_batch(limit=2, concurrency=2, fetch_readme=False)

        self.assertEqual(result["counts"], {"succeeded": 1, "failed": 1})

    def test_concurrent_dry_run_does_not_load_embedding_model(self) -> None:
        projects = [{**PROJECT, "repo_id": f"owner/repo-{index}"} for index in range(2)]
        db = MagicMock()
        db.list_github_projects_for_semantic_sync.return_value = projects
        indexer = GitHubProjectSemanticIndexer(db=db)

        with patch.object(indexer, "_embeddings") as embeddings:
            result = indexer.sync_batch(limit=2, concurrency=2, fetch_readme=False, dry_run=True)

        self.assertEqual(result["counts"], {"dry_run": 2})
        embeddings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
