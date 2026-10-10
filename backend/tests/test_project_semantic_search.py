from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock, patch

from backend.app.services import project_semantic_search as semantic


class ProjectSemanticSearchTests(unittest.TestCase):
    def tearDown(self) -> None:
        shared = semantic._shared_project_semantic_search
        semantic._shared_project_semantic_search = None
        if shared is not None:
            try:
                shared.close()
            except Exception:
                pass

    def test_shared_accessor_constructs_one_instance_concurrently(self) -> None:
        instances = []

        def get_instance() -> None:
            instances.append(semantic.get_project_semantic_search())

        threads = [threading.Thread(target=get_instance) for _ in range(8)]
        with patch.object(semantic, "ProjectSemanticSearch", wraps=semantic.ProjectSemanticSearch) as factory:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(factory.call_count, 1)
        self.assertTrue(all(instance is instances[0] for instance in instances))

    def test_embedding_model_is_initialized_once_concurrently(self) -> None:
        vectors = MagicMock()
        embeddings = MagicMock()
        embeddings.embed_query.return_value = [0.1, 0.2]
        search = semantic.ProjectSemanticSearch(vectors=vectors)

        with patch(
            "backend.app.core.model_factory.get_embedding_model",
            return_value=embeddings,
        ) as factory:
            threads = [threading.Thread(target=search.warmup) for _ in range(5)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        factory.assert_called_once_with()

    def test_bilingual_variants_are_fused_by_reciprocal_rank(self) -> None:
        vectors = MagicMock()
        vectors.search_repo_ids.side_effect = [
            [
                semantic.ProjectSemanticHit("owner/a", 0.9),
                semantic.ProjectSemanticHit("owner/b", 0.8),
            ],
            [
                semantic.ProjectSemanticHit("owner/b", 0.95),
                semantic.ProjectSemanticHit("owner/c", 0.7),
            ],
        ]
        embeddings = MagicMock()
        embeddings.embed_query.side_effect = [[0.1, 0.2], [0.3, 0.4]]
        search = semantic.ProjectSemanticSearch(vectors=vectors, embeddings=embeddings)

        with patch.object(semantic.settings, "project_semantic_search_enabled", True):
            hits = search.search_repo_ids("智能体工作流")

        self.assertEqual([hit.repo_id for hit in hits], ["owner/b", "owner/a", "owner/c"])
        self.assertEqual(embeddings.embed_query.call_count, 2)
        self.assertEqual(vectors.search_repo_ids.call_count, 2)

    def test_rrf_deduplicates_each_ranking_and_breaks_ties_by_repo_id(self) -> None:
        rankings = [
            [
                semantic.ProjectSemanticHit("owner/b", 0.9),
                semantic.ProjectSemanticHit("owner/b", 0.8),
            ],
            [semantic.ProjectSemanticHit("owner/a", 0.9)],
        ]

        hits = semantic.reciprocal_rank_fusion(rankings, rank_constant=60, limit=10)

        self.assertEqual([hit.repo_id for hit in hits], ["owner/a", "owner/b"])

    def test_warmup_covers_topics_at_search_depth_without_reembedding(self) -> None:
        vectors = MagicMock()
        embeddings = MagicMock()
        embeddings.embed_query.return_value = [0.1, 0.2]
        search = semantic.ProjectSemanticSearch(vectors=vectors, embeddings=embeddings)

        with (
            patch.object(semantic.settings, "project_semantic_chunk_limit", 800),
            patch.object(semantic.settings, "project_semantic_repo_limit", 200),
            patch.object(semantic.settings, "project_semantic_min_score", 0.45),
        ):
            search.warmup()
            first_embeddings = embeddings.embed_query.call_count
            search.warmup()

        queries = [call.args[0] for call in embeddings.embed_query.call_args_list]
        for topic in ("AI 编程助手", "知识库问答", "自托管书签管理"):
            self.assertIn(topic, queries)
            self.assertTrue(any(query.startswith(topic + " ") for query in queries))
        self.assertEqual(embeddings.embed_query.call_count, first_embeddings)
        self.assertEqual(vectors.search_repo_ids.call_count, first_embeddings * 2)
        for call in vectors.search_repo_ids.call_args_list:
            self.assertEqual(call.kwargs, {
                "chunk_limit": 800, "repo_limit": 200, "min_score": 0.45,
            })

    def test_warmup_keeps_bounded_recent_queries_without_reembedding_them(self) -> None:
        vectors = MagicMock()
        vectors.search_repo_ids.return_value = []
        embeddings = MagicMock()
        embedding_by_query = {"a": [1.0], "b": [2.0], "c": [3.0], "seed": [0.0]}
        embeddings.embed_query.side_effect = embedding_by_query.__getitem__
        search = semantic.ProjectSemanticSearch(vectors=vectors, embeddings=embeddings)
        with (
            patch.object(semantic.settings, "project_semantic_search_enabled", True),
            patch.object(semantic, "_WARMUP_QUERIES", ("seed",)),
            patch.object(semantic, "_RECENT_WARMUP_VECTOR_LIMIT", 2),
        ):
            for query in ("a", "b", "a", "c"):
                self.assertEqual(search.search_repo_ids(query), [])
            vectors.search_repo_ids.reset_mock()
            embeddings.embed_query.reset_mock()
            search.warmup()

        embeddings.embed_query.assert_called_once_with("seed")
        self.assertEqual(
            [call.args[0] for call in vectors.search_repo_ids.call_args_list],
            [[0.0], [1.0], [3.0]],
        )

    def test_warmup_retries_failed_embedding_without_discarding_progress(self) -> None:
        vectors = MagicMock()
        embeddings = MagicMock()
        embeddings.embed_query.side_effect = [[0.1], RuntimeError("temporary"), [0.2]]
        search = semantic.ProjectSemanticSearch(vectors=vectors, embeddings=embeddings)
        with patch.object(semantic, "_WARMUP_QUERIES", ("one", "two")):
            with self.assertRaisesRegex(RuntimeError, "temporary"):
                search.warmup()
            search.warmup()
            search.warmup()

        self.assertEqual(embeddings.embed_query.call_count, 3)
        self.assertEqual(vectors.search_repo_ids.call_count, 4)

    def test_disabled_warmup_does_not_initialize_dependencies(self) -> None:
        with (
            patch.object(semantic.settings, "project_semantic_search_enabled", False),
            patch.object(semantic, "get_project_semantic_search") as get_search,
        ):
            result = semantic.warmup_project_semantic_search()

        self.assertEqual(result, {"status": "disabled"})
        get_search.assert_not_called()

    def test_warmup_failure_is_non_fatal_and_retryable(self) -> None:
        search = MagicMock()
        search.warmup.side_effect = [RuntimeError("temporary"), None]
        with (
            patch.object(semantic.settings, "project_semantic_search_enabled", True),
            patch.object(semantic, "get_project_semantic_search", return_value=search),
        ):
            failed = semantic.warmup_project_semantic_search()
            succeeded = semantic.warmup_project_semantic_search()

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(succeeded["status"], "success")


if __name__ == "__main__":
    unittest.main()
