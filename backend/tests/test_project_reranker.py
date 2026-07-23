from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from backend.app.services import project_reranker


class ProjectRerankerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = SimpleNamespace(
            project_reranker_enabled=True,
            project_reranker_url="https://api.siliconflow.cn/v1/rerank",
            project_reranker_model_name="test-reranker",
            project_reranker_timeout_seconds=1.0,
            project_reranker_candidate_limit=20,
            project_reranker_min_candidates=2,
            siliconflow_api_key="secret",
        )
        self.projects = [
            {"full_name": "owner/a", "description": "agent tutorial"},
            {"full_name": "owner/b", "description": "agent framework"},
        ]

    def test_valid_response_reorders_candidates(self) -> None:
        response = httpx.Response(
            200,
            request=httpx.Request("POST", self.settings.project_reranker_url),
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.1},
                    {"index": 1, "relevance_score": 0.9},
                ]
            },
        )
        client = AsyncMock()
        client.post.return_value = response
        reranker = project_reranker.ProjectReranker(client=client)

        with patch.object(project_reranker, "settings", self.settings):
            ranked = asyncio.run(reranker.rerank_repo_ids("learn agent", self.projects))

        self.assertEqual(ranked, ["owner/b", "owner/a"])
        payload = client.post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "test-reranker")
        self.assertNotIn("secret", str(payload))

    def test_malformed_response_fails_open(self) -> None:
        response = httpx.Response(
            200,
            request=httpx.Request("POST", self.settings.project_reranker_url),
            json={"results": [{"index": 1, "relevance_score": "not-a-score"}]},
        )
        client = AsyncMock()
        client.post.return_value = response
        reranker = project_reranker.ProjectReranker(client=client)

        with patch.object(project_reranker, "settings", self.settings):
            ranked = asyncio.run(reranker.rerank_repo_ids("learn agent", self.projects))

        self.assertEqual(ranked, ["owner/a", "owner/b"])

    def test_timeout_fails_open(self) -> None:
        client = AsyncMock()
        client.post.side_effect = httpx.TimeoutException("slow")
        reranker = project_reranker.ProjectReranker(client=client)

        with patch.object(project_reranker, "settings", self.settings):
            ranked = asyncio.run(reranker.rerank_repo_ids("learn agent", self.projects))

        self.assertEqual(ranked, ["owner/a", "owner/b"])

    def test_unapproved_endpoint_does_not_receive_api_key(self) -> None:
        client = AsyncMock()
        reranker = project_reranker.ProjectReranker(client=client)
        self.settings.project_reranker_url = "https://example.test/v1/rerank"

        with patch.object(project_reranker, "settings", self.settings):
            ranked = asyncio.run(reranker.rerank_repo_ids("learn agent", self.projects))

        self.assertEqual(ranked, ["owner/a", "owner/b"])
        client.post.assert_not_called()

    def test_disabled_reranker_skips_request(self) -> None:
        client = AsyncMock()
        reranker = project_reranker.ProjectReranker(client=client)
        self.settings.project_reranker_enabled = False

        with patch.object(project_reranker, "settings", self.settings):
            ranked = asyncio.run(reranker.rerank_repo_ids("learn agent", self.projects))

        self.assertEqual(ranked, ["owner/a", "owner/b"])
        client.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
