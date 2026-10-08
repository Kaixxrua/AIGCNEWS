import asyncio
from unittest.mock import MagicMock

import pytest

from backend.app.repositories.project_catalog import ProjectLexicalCandidate, ProjectLexicalCandidateLanes
from backend.app.services import project_discovery


@pytest.mark.parametrize("error", ["HTTP 403", "HTTP 429", "GitHub fallback is disabled."])
def test_returned_fallback_errors_preserve_relaxed_local_matches(monkeypatch, error):
    class Catalog:
        find_lexical_candidate_repo_ids = MagicMock(return_value=[])
        find_lexical_candidate_lanes = MagicMock(return_value=ProjectLexicalCandidateLanes(
            relaxed=(ProjectLexicalCandidate("owner/local", "relaxed", term_coverage=1),),
        ))
        list_projects = MagicMock(return_value={"items": [{"full_name": "owner/local"}], "total": 1})

    monkeypatch.setattr(project_discovery.settings, "project_ai_search_strategy", "v2")
    monkeypatch.setattr(project_discovery.settings, "project_semantic_search_enabled", False)
    monkeypatch.setattr(project_discovery.settings, "project_reranker_enabled", False)
    fallback = MagicMock(return_value={"items": [], "error": error})
    result = asyncio.run(project_discovery.search_projects(
        query="windows screenshot", repository_factory=Catalog, fallback_search=fallback,
    ))
    fallback.assert_called_once()
    assert result["total"] == result["local_total"] == 1
    assert result["items"][0]["full_name"] == "owner/local"
    assert result["result_origin"] == "aigc_news_local"
    assert result["fallback_error"] == error
