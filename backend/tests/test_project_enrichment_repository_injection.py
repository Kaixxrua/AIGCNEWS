from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.app.repositories.application_repository_context import (
    configure_application_repositories,
)
from backend.app.repositories.project_write_repository import (
    GitHubProjectEnrichmentRepository,
    GitHubProjectSemanticSourceRepository,
    ToolWebsiteEnrichmentRepository,
)
from backend.app.services.indexing import github_project_semantic_indexer
from backend.app.services.ingestion import github_project_enricher
from backend.app.services.ingestion.tool_website_enricher import ToolWebsiteEnricher


def test_enrichment_helper_forwards_explicit_repository(monkeypatch) -> None:
    repository = MagicMock(spec=GitHubProjectEnrichmentRepository)
    enricher = MagicMock()
    enricher.enrich_batch.return_value = {"status": "success"}
    enricher_type = MagicMock(return_value=enricher)
    monkeypatch.setattr(github_project_enricher, "GitHubProjectEnricher", enricher_type)

    result = github_project_enricher.enrich_github_projects(
        limit=3,
        db=repository,
    )

    assert result == {"status": "success"}
    enricher_type.assert_called_once_with(db=repository)
    assert enricher.enrich_batch.call_args.kwargs["limit"] == 3


def test_enricher_default_uses_configured_application_repository(monkeypatch) -> None:
    repository = MagicMock(spec=GitHubProjectEnrichmentRepository)
    repository.runtime_provider_settings.get_runtime_provider_setting.return_value = {}
    configure_application_repositories(
        SimpleNamespace(github_enrichment=repository)
    )
    monkeypatch.setattr(github_project_enricher, "get_chat_model", MagicMock())
    try:
        enricher = github_project_enricher.GitHubProjectEnricher()
    finally:
        configure_application_repositories(None)

    assert enricher.db is repository


def test_tool_website_enricher_default_uses_configured_repository() -> None:
    repository = MagicMock(spec=ToolWebsiteEnrichmentRepository)
    repository.runtime_provider_settings.get_runtime_provider_setting.return_value = {}
    configure_application_repositories(
        SimpleNamespace(tool_website_enrichment=repository)
    )
    try:
        enricher = ToolWebsiteEnricher()
    finally:
        configure_application_repositories(None)

    assert enricher.db is repository


def test_semantic_helper_forwards_explicit_repository(monkeypatch) -> None:
    repository = MagicMock(spec=GitHubProjectSemanticSourceRepository)
    indexer = MagicMock()
    indexer.sync_batch.return_value = {"status": "success"}
    indexer_type = MagicMock(return_value=indexer)
    monkeypatch.setattr(
        github_project_semantic_indexer.settings,
        "project_semantic_indexing_enabled",
        True,
    )
    monkeypatch.setattr(
        github_project_semantic_indexer,
        "GitHubProjectSemanticIndexer",
        indexer_type,
    )

    result = github_project_semantic_indexer.sync_github_project_semantic_index(
        db=repository,
        limit=4,
    )

    assert result == {"status": "success"}
    indexer_type.assert_called_once_with(db=repository)
    indexer.sync_batch.assert_called_once_with(limit=4)


def test_semantic_indexer_default_uses_configured_repository() -> None:
    repository = MagicMock(spec=GitHubProjectSemanticSourceRepository)
    configure_application_repositories(
        SimpleNamespace(github_semantic_sources=repository)
    )
    try:
        indexer = github_project_semantic_indexer.GitHubProjectSemanticIndexer()
    finally:
        configure_application_repositories(None)

    assert indexer.db is repository
