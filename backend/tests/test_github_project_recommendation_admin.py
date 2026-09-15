from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

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
    # running 标记由服务层补充：无批处理运行时恒为 False
    assert enrichment == {"total": 12, "enriched": 7, "running": False}
    status.get_github_project_enrichment_status.assert_called_once_with()


def test_enrichment_pages_forwards_independent_page_state() -> None:
    status = MagicMock()
    status.list_github_project_enrichment_pages.return_value = {
        "unprocessable": {"items": [], "total": 0, "page": 2, "page_size": 15},
        "retained": {"items": [], "total": 0, "page": 3, "page_size": 15},
    }
    service = GitHubProjectRecommendationAdminService(MagicMock(), status)

    result = asyncio.run(service.get_enrichment_pages(
        unprocessable_page=2,
        retained_page=3,
        page_size=15,
    ))

    assert result["unprocessable"]["page"] == 2
    assert result["retained"]["page"] == 3
    status.list_github_project_enrichment_pages.assert_called_once_with(
        unprocessable_page=2,
        retained_page=3,
        page_size=15,
    )


def test_enrichment_status_marks_running_batch() -> None:
    status = MagicMock()
    status.get_github_project_enrichment_status.return_value = {"total": 3, "enriched": 1}
    service = GitHubProjectRecommendationAdminService(MagicMock(), status)

    with patch(
        "backend.app.services.ingestion.github_project_enricher.github_enrichment_batch_running",
        return_value=True,
    ):
        enrichment = asyncio.run(service.get_enrichment_status())

    assert enrichment["running"] is True
