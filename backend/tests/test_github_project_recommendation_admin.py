from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from backend.app.services.github_project_recommendation_admin import (
    GitHubProjectAdminNotFoundError,
    GitHubProjectAdminValidationError,
    GitHubProjectRecommendationAdminService,
)


def test_recommend_normalizes_admin_identity_and_forwards_project_selector() -> None:
    recommendations = MagicMock()
    recommendations.recommend_github_project.return_value = {
        "repo_id": "repo-1",
        "is_recommended": True,
    }
    status = MagicMock()
    service = GitHubProjectRecommendationAdminService(recommendations, status)

    outcome = asyncio.run(
        service.recommend(
            repo_id="repo-1",
            full_name="",
            admin_identity={"sub": "9"},
        )
    )

    recommendations.recommend_github_project.assert_called_once_with(
        repo_id="repo-1",
        full_name="",
        recommended_by_user_id=9,
    )
    assert outcome.message == "已加入站长推荐。"


def test_recommend_maps_repository_validation_and_missing_errors() -> None:
    recommendations = MagicMock()
    status = MagicMock()
    service = GitHubProjectRecommendationAdminService(recommendations, status)

    recommendations.recommend_github_project.side_effect = ValueError("selector required")
    with pytest.raises(GitHubProjectAdminValidationError, match="selector required"):
        asyncio.run(service.recommend(repo_id="", full_name="", admin_identity=None))

    recommendations.recommend_github_project.side_effect = LookupError("missing")
    with pytest.raises(GitHubProjectAdminNotFoundError, match="missing"):
        asyncio.run(service.recommend(repo_id="missing", full_name="", admin_identity={}))


def test_unrecommend_projects_removed_message_and_reads_status() -> None:
    recommendations = MagicMock()
    recommendations.unrecommend_github_project.side_effect = [
        {"repo_id": "repo-1", "removed": True},
        {"repo_id": "repo-1", "removed": False},
    ]
    status = MagicMock()
    status.get_github_project_enrichment_status.return_value = {
        "total": 12,
        "enriched": 7,
    }
    service = GitHubProjectRecommendationAdminService(recommendations, status)

    removed = asyncio.run(service.unrecommend(repo_id="repo-1", full_name=""))
    unchanged = asyncio.run(service.unrecommend(repo_id="repo-1", full_name=""))
    enrichment = asyncio.run(service.get_enrichment_status())

    assert removed.message == "已取消站长推荐。"
    assert unchanged.message == "该项目当前不是站长推荐。"
    assert enrichment == {"total": 12, "enriched": 7}
    status.get_github_project_enrichment_status.assert_called_once_with()
