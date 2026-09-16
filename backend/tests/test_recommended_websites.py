from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

from backend.app.api.routes_recommended_websites import get_recommended_website_repository, router
from backend.app.core.auth import RequireUser
from backend.app.repositories.recommended_website_repository import DuplicateRecommendedWebsiteError

PAYLOAD = {"title": "Example", "url": "https://example.com/", "description": "Useful website", "category": "Tools", "sort_order": 0}
ROW = {**PAYLOAD, "id": 1, "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}


@pytest.fixture
def setup_api():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    repository = MagicMock()
    repository.list_websites.return_value = []
    repository.create_website.return_value = ROW
    repository.update_website.return_value = ROW
    repository.delete_website.return_value = True
    app.dependency_overrides[get_recommended_website_repository] = lambda: repository
    return app, repository


@pytest.mark.asyncio
async def test_public_empty_directory_and_openapi_are_available_without_auth(setup_api):
    app, repository = setup_api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/site/recommended-websites")
        assert response.status_code == 200
        assert response.json() == {"items": []}
        assert (await client.get("/docs")).status_code == 200
        schema = (await client.get("/openapi.json")).json()
        assert "post" in schema["paths"]["/api/ops/recommended-websites"]
    repository.list_websites.assert_called_once_with()
    repository.create_website.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [
    ("post", "/api/ops/recommended-websites"),
    ("put", "/api/ops/recommended-websites/1"),
    ("delete", "/api/ops/recommended-websites/1"),
])
@pytest.mark.parametrize("role,expected", [(None, 401), ("user", 403)])
async def test_writes_require_actual_admin_role(setup_api, method, path, role, expected):
    app, repository = setup_api
    if role:
        app.dependency_overrides[RequireUser] = lambda: {"id": 7, "role": role}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, path, json=PAYLOAD)
    assert response.status_code == expected
    repository.create_website.assert_not_called()
    repository.update_website.assert_not_called()
    repository.delete_website.assert_not_called()


@pytest.mark.asyncio
async def test_admin_crud_uses_only_the_dedicated_directory(setup_api):
    app, repository = setup_api
    app.dependency_overrides[RequireUser] = lambda: {"id": 7, "role": "admin"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/ops/recommended-websites", json={**PAYLOAD, "url": "https://EXAMPLE.COM"})
        assert created.status_code == 201
        repository.create_website.assert_called_once_with(**PAYLOAD)
        repository.list_websites.return_value = [ROW]
        listed = await client.get("/api/site/recommended-websites")
        assert listed.json()["items"][0]["url"] == PAYLOAD["url"]
        assert "user_id" not in listed.json()["items"][0]
        assert (await client.put("/api/ops/recommended-websites/1", json=PAYLOAD)).status_code == 200
        repository.update_website.assert_called_once_with(1, **PAYLOAD)
        removed = await client.delete("/api/ops/recommended-websites/1")
        assert removed.status_code == 204 and removed.content == b""
        repository.delete_website.assert_called_once_with(1)


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [
    {"title": "  "}, {"url": "javascript:alert(1)"}, {"url": "data:text/html,hello"},
    {"url": "ftp://example.com/"}, {"url": "https://name:secret@example.com/"},
    {"url": "https://exam\nple.com/"}, {"sort_order": 10001}, {"private_collection_id": 42},
])
async def test_invalid_or_unsafe_inputs_are_rejected_before_storage(setup_api, overrides):
    app, repository = setup_api
    app.dependency_overrides[RequireUser] = lambda: {"id": 7, "role": "admin"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/ops/recommended-websites", json={**PAYLOAD, **overrides})
    assert response.status_code == 422
    repository.create_website.assert_not_called()


@pytest.mark.asyncio
async def test_duplicates_and_missing_recommendations_have_explicit_statuses(setup_api):
    app, repository = setup_api
    app.dependency_overrides[RequireUser] = lambda: {"id": 7, "role": "admin"}
    repository.create_website.side_effect = DuplicateRecommendedWebsiteError
    repository.update_website.side_effect = DuplicateRecommendedWebsiteError
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/ops/recommended-websites", json=PAYLOAD)).status_code == 409
        assert (await client.put("/api/ops/recommended-websites/1", json=PAYLOAD)).status_code == 409
        repository.update_website.side_effect = None
        repository.update_website.return_value = None
        repository.delete_website.return_value = False
        assert (await client.put("/api/ops/recommended-websites/99", json=PAYLOAD)).status_code == 404
        assert (await client.delete("/api/ops/recommended-websites/99")).status_code == 404
