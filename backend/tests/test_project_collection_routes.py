from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_github_projects
from backend.app.api.dependencies import (
    get_tool_website_enrichment_repository,
    get_user_project_collection_repository,
)
from backend.app.core.auth import RequireUser
from backend.app.repositories.project_write_repository import (
    ToolWebsiteEnrichmentRepository,
    UserProjectCollectionRepository,
)


def _client(
    repository: UserProjectCollectionRepository,
    enrichment: ToolWebsiteEnrichmentRepository | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(routes_github_projects.router, prefix="/api")
    app.dependency_overrides[RequireUser] = lambda: {"user_id": 7}
    app.dependency_overrides[
        get_user_project_collection_repository
    ] = lambda: repository
    if enrichment is not None:
        app.dependency_overrides[
            get_tool_website_enrichment_repository
        ] = lambda: enrichment
    return TestClient(app)


def test_collection_routes_use_injected_repository() -> None:
    repository = MagicMock(spec=UserProjectCollectionRepository)
    repository.list_user_project_collection.return_value = {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 24,
        "has_next": False,
    }
    repository.get_user_project_categories.return_value = {
        "items": [],
        "total": 0,
    }
    repository.get_user_project_tags.return_value = {
        "items": [{"label": "agent", "count": 2}],
        "total": 1,
    }
    client = _client(repository)

    collection = client.get("/api/projects/me/collection?source=website")
    categories = client.get("/api/projects/me/categories?source=website")
    tags = client.get("/api/projects/me/tags?source=website")

    assert collection.status_code == 200
    assert collection.json()["source"] == "website"
    assert categories.status_code == 200
    assert categories.json()["source"] == "website"
    assert tags.status_code == 200
    assert tags.json()["items"] == [{"label": "agent", "count": 2}]
    assert repository.list_user_project_collection.call_args.kwargs["user_id"] == 7
    assert repository.list_user_project_collection.call_args.kwargs["source"] == "website"
    repository.get_user_project_categories.assert_called_once_with(
        user_id=7,
        source="website",
        min_stars=500,
        enriched_only=True,
    )
    repository.get_user_project_tags.assert_called_once_with(
        user_id=7,
        source="website",
        min_stars=500,
        enriched_only=True,
    )


def test_favorite_routes_use_injected_repository() -> None:
    repository = MagicMock(spec=UserProjectCollectionRepository)
    repository.add_project_favorite.return_value = {
        "source": "github",
        "repo_id": "repo-1",
        "is_favorited": True,
    }
    repository.remove_project_favorite.return_value = True
    client = _client(repository)

    added = client.post(
        "/api/projects/me/favorites",
        json={"source": "github", "repo_id": "repo-1"},
    )
    removed = client.delete(
        "/api/projects/me/favorites?source=github&repo_id=repo-1"
    )

    assert added.status_code == 200
    assert added.json()["is_favorited"] is True
    assert removed.status_code == 200
    assert removed.json()["deleted"] is True
    repository.add_project_favorite.assert_called_once_with(
        user_id=7,
        source="github",
        repo_id="repo-1",
        website_id=None,
    )
    repository.remove_project_favorite.assert_called_once_with(
        user_id=7,
        source="github",
        repo_id="repo-1",
        website_id=None,
    )


def test_personal_website_add_uses_both_injected_repositories(monkeypatch) -> None:
    collection = MagicMock(spec=UserProjectCollectionRepository)
    enrichment = MagicMock(spec=ToolWebsiteEnrichmentRepository)
    collection.link_user_tool_website.return_value = {"user_added": True}
    collection.get_tool_website_item_for_user.return_value = {
        "website_id": 11,
        "title": "My Tool",
    }
    enricher = MagicMock()
    enricher.add_and_enrich.return_value = {
        "item": {"website_id": 11},
        "duplicate": False,
        "enrichment_failed": False,
    }
    monkeypatch.setattr(
        "backend.app.services.ingestion.tool_website_enricher.ToolWebsiteEnricher",
        MagicMock(return_value=enricher),
    )
    client = _client(collection, enrichment)

    response = client.post(
        "/api/projects/me/tool-websites",
        json={"url": "https://example.test"},
    )

    assert response.status_code == 200
    assert response.json()["item"]["user_added"] is True
    enricher.add_and_enrich.assert_called_once_with(
        "https://example.test",
        added_by_user_id=7,
        visibility="private",
    )
    collection.link_user_tool_website.assert_called_once_with(
        user_id=7,
        website_id=11,
        added_via="auto",
    )
    collection.get_tool_website_item_for_user.assert_called_once_with(
        user_id=7,
        website_id=11,
    )


def test_personal_website_update_and_remove_use_injected_repository() -> None:
    repository = MagicMock(spec=UserProjectCollectionRepository)
    repository.upsert_user_tool_website_override.return_value = {
        "website_id": 11,
        "title": "My Tool",
    }
    repository.unlink_user_tool_website.return_value = True
    client = _client(repository)

    updated = client.patch(
        "/api/projects/me/tool-websites/11",
        json={
            "title": "My Tool",
            "description": "Description",
            "description_zh": "说明",
            "category_slug": "agent",
            "subcategory_slug": "workflow",
            "tags": ["agent"],
            "image_url": "https://example.test/icon.png",
        },
    )
    removed = client.delete("/api/projects/me/tool-websites/11")

    assert updated.status_code == 200
    assert updated.json()["item"]["title"] == "My Tool"
    assert removed.status_code == 200
    payload = repository.upsert_user_tool_website_override.call_args.args[0]
    assert payload["user_id"] == 7
    assert payload["website_id"] == 11
    assert payload["tags"] == ["agent"]
    repository.unlink_user_tool_website.assert_called_once_with(
        user_id=7,
        website_id=11,
    )
