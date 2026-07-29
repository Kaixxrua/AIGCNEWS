from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_github_projects
from backend.app.api.dependencies import get_personal_projects_service
from backend.app.core.auth import OptionalUser, RequireUser
from backend.app.services.personal_projects import (
    InvalidPersonalProjectRequest,
    PersonalProjectNotFound,
    PersonalProjectsService,
    PersonalWebsiteOperationFailed,
)


def _service() -> AsyncMock:
    return AsyncMock(spec=PersonalProjectsService)


def _client(service: PersonalProjectsService) -> TestClient:
    app = FastAPI()
    app.include_router(routes_github_projects.router, prefix="/api")
    app.dependency_overrides[RequireUser] = lambda: {"user_id": 7}
    app.dependency_overrides[get_personal_projects_service] = lambda: service
    return TestClient(app)


def test_legacy_github_projects_route_uses_catalog_repository(monkeypatch) -> None:
    repository = MagicMock()
    repository.list_projects.return_value = {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 24,
    }
    monkeypatch.setattr(
        routes_github_projects,
        "get_project_catalog_repository",
        MagicMock(return_value=repository),
    )
    app = FastAPI()
    app.include_router(routes_github_projects.router, prefix="/api")
    app.dependency_overrides[OptionalUser] = lambda: None

    response = TestClient(app).get("/api/github/projects?q=agent")

    assert response.status_code == 200
    repository.list_projects.assert_called_once_with(
        source="github",
        scope="all",
        category="",
        subcategory="",
        q="agent",
        language="",
        page=1,
        page_size=24,
        sort="stars",
        min_stars=500,
        enriched_only=True,
        user_id=None,
    )


def test_collection_routes_use_injected_service_and_normalize_queries() -> None:
    service = _service()
    service.list_collection.return_value = {
        "items": [], "total": 0, "page": 1, "page_size": 24
    }
    service.get_categories.return_value = {"items": [], "total": 0}
    service.get_tags.return_value = {
        "items": [{"label": "agent", "count": 2}], "total": 1
    }
    client = _client(service)

    collection = client.get(
        "/api/projects/me/collection?source=website&category=%20agent%20&q=%20rag%20"
    )
    categories = client.get("/api/projects/me/categories?source=website")
    tags = client.get("/api/projects/me/tags?source=website")

    assert collection.status_code == 200
    assert collection.json()["source"] == "website"
    assert categories.status_code == 200
    assert categories.json()["source"] == "website"
    assert tags.status_code == 200
    assert tags.json()["items"] == [{"label": "agent", "count": 2}]
    assert service.list_collection.call_args.kwargs["user_id"] == 7
    assert service.list_collection.call_args.kwargs["source"] == "website"
    assert service.list_collection.call_args.kwargs["category"] == "agent"
    assert service.list_collection.call_args.kwargs["q"] == "rag"
    service.get_categories.assert_awaited_once_with(
        user_id=7, source="website", min_stars=500, enriched_only=True
    )
    service.get_tags.assert_awaited_once_with(
        user_id=7, source="website", min_stars=500, enriched_only=True
    )


def test_favorite_routes_use_injected_service() -> None:
    service = _service()
    service.add_favorite.return_value = {
        "source": "github", "repo_id": "repo-1", "is_favorited": True
    }
    service.remove_favorite.return_value = True
    client = _client(service)

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
    service.add_favorite.assert_awaited_once_with(
        user_id=7, source="github", repo_id="repo-1", website_id=None
    )
    service.remove_favorite.assert_awaited_once_with(
        user_id=7, source="github", repo_id="repo-1", website_id=None
    )


def test_favorite_route_maps_service_domain_errors() -> None:
    service = _service()
    service.add_favorite.side_effect = InvalidPersonalProjectRequest("repo_id 不能为空")
    service.remove_favorite.side_effect = PersonalProjectNotFound("GitHub 项目不存在")
    client = _client(service)

    invalid = client.post(
        "/api/projects/me/favorites", json={"source": "github"}
    )
    missing = client.delete(
        "/api/projects/me/favorites?source=github&repo_id=missing"
    )

    assert invalid.status_code == 400
    assert invalid.json() == {"detail": "repo_id 不能为空"}
    assert missing.status_code == 404
    assert missing.json() == {"detail": "GitHub 项目不存在"}


def test_personal_website_routes_use_injected_service() -> None:
    service = _service()
    service.add_tool_website.return_value = {
        "status": "succeeded",
        "message": "工具网站已添加到我的收藏。",
        "duplicate": False,
        "item": {"website_id": 11, "user_added": True},
    }
    service.update_tool_website.return_value = {"website_id": 11, "title": "My Tool"}
    service.remove_tool_website.return_value = True
    client = _client(service)

    added = client.post(
        "/api/projects/me/tool-websites", json={"url": " https://example.test "}
    )
    updated = client.patch(
        "/api/projects/me/tool-websites/11",
        json={
            "title": "My Tool", "description": "Description", "description_zh": "说明",
            "category_slug": "agent", "subcategory_slug": "workflow",
            "tags": ["agent"], "image_url": "https://example.test/icon.png",
        },
    )
    removed = client.delete("/api/projects/me/tool-websites/11")

    assert added.status_code == 200
    assert added.json()["item"]["user_added"] is True
    assert updated.status_code == 200
    assert updated.json()["item"]["title"] == "My Tool"
    assert removed.status_code == 200
    service.add_tool_website.assert_awaited_once_with(
        user_id=7, url=" https://example.test "
    )
    assert service.update_tool_website.call_args.kwargs["user_id"] == 7
    assert service.update_tool_website.call_args.kwargs["website_id"] == 11
    service.remove_tool_website.assert_awaited_once_with(user_id=7, website_id=11)


def test_personal_website_route_maps_operation_failure() -> None:
    service = _service()
    service.add_tool_website.side_effect = PersonalWebsiteOperationFailed(
        "工具网站添加或富化失败：upstream unavailable"
    )
    client = _client(service)

    response = client.post(
        "/api/projects/me/tool-websites", json={"url": "https://example.test"}
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "工具网站添加或富化失败：upstream unavailable"
    }


def test_personal_routes_do_not_orchestrate_collection_or_enricher_directly() -> None:
    route_path = Path(routes_github_projects.__file__)
    module = ast.parse(route_path.read_text(encoding="utf-8"), filename=str(route_path))
    personal_routes = {
        decorator.args[0].value
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.args
        and isinstance(decorator.args[0], ast.Constant)
        and isinstance(decorator.args[0].value, str)
        and decorator.args[0].value.startswith("/projects/me/")
    }
    imports = {
        alias.name
        for node in module.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    direct_calls = {
        node.func.attr
        for function in module.body
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(decorator, ast.Call)
            and decorator.args
            and isinstance(decorator.args[0], ast.Constant)
            and str(decorator.args[0].value).startswith("/projects/me/")
            for decorator in function.decorator_list
        )
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert personal_routes == {
        "/projects/me/collection",
        "/projects/me/categories",
        "/projects/me/tags",
        "/projects/me/favorites",
        "/projects/me/tool-websites",
        "/projects/me/tool-websites/manual",
        "/projects/me/tool-websites/{website_id}",
    }
    assert "ToolWebsiteEnricher" not in imports
    assert not direct_calls & {
        "list_user_project_collection", "get_user_project_categories",
        "get_user_project_tags", "add_project_favorite", "remove_project_favorite",
        "link_user_tool_website", "get_tool_website_item_for_user",
        "upsert_user_tool_website_override", "unlink_user_tool_website",
    }
