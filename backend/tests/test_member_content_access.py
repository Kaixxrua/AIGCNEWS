from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_github_projects, routes_report, routes_search
from backend.app.api.dependencies import (
    get_briefing_repository,
    get_document_repository,
    get_project_catalog_query_service,
)
from backend.app.core.auth import create_access_token, get_user_identity_repository
from backend.app.core.config import settings
from backend.app.services.briefing.preview import briefing_preview


@pytest.fixture
def client_and_data(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "member-content-test-signing-key-only" * 2)
    app = FastAPI()
    for router in (routes_github_projects.router, routes_report.router, routes_search.router):
        app.include_router(router, prefix="/api")
    catalog = MagicMock()
    catalog.list_public_projects = AsyncMock()
    briefings = MagicMock()
    content = "# Issue\n\n" + "Public introduction. " * 30 + "\n\n" + "Members-only details. " * 150
    briefings.get_briefing_by_date.return_value = {
        "id": 42,
        "date": "2026-10-09",
        "content": content,
        "content_zh": content,
        "content_en": content.replace("Issue", "English issue"),
    }
    briefings.get_briefing.return_value = briefings.get_briefing_by_date.return_value
    app.dependency_overrides[get_project_catalog_query_service] = lambda: catalog
    app.dependency_overrides[get_briefing_repository] = lambda: briefings
    app.dependency_overrides[get_document_repository] = MagicMock
    app.dependency_overrides[get_user_identity_repository] = lambda: None
    return TestClient(app), catalog, briefings


def sign_in(client):
    users = MagicMock()
    users.get_user_by_id.return_value = {
        "user_id": 7,
        "role": "user",
        "membership_tier": "free",
        "pwd_ver": 1,
    }
    client.app.dependency_overrides[get_user_identity_repository] = lambda: users
    client.headers["Authorization"] = "Bearer " + create_access_token({"user_id": 7, "pwd_ver": 1})
    return users


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
@pytest.mark.parametrize(
    "path",
    [
        "/api/projects?q=agent",
        "/api/projects?page=2",
        "/api/projects?page=999&page_size=60",
        "/api/search?q=agent",
        "/api/report/latest",
        "/api/report/42",
    ],
)
def test_guest_cannot_read_protected_content(client_and_data, headers, path):
    client, catalog, briefings = client_and_data
    response = client.get(path, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    catalog.list_public_projects.assert_not_called()
    briefings.get_briefing_by_date.assert_not_called()
    briefings.get_briefing.assert_not_called()


def test_guest_first_page_is_capped_and_has_no_search(client_and_data):
    client, catalog, _ = client_and_data
    # Only arguments matter here; an empty repository response exercises the
    # existing response adapter through the established route contract suite.
    from types import SimpleNamespace

    catalog.min_stars = 500
    catalog.list_public_projects.return_value = SimpleNamespace(
        result={"items": [], "total": 100, "page": 1, "page_size": 24},
        effective_sort="stars",
    )
    response = client.get("/api/projects?q=%20%20&page_size=60")
    assert response.status_code == 200
    assert response.json()["page_size"] == 24
    assert catalog.list_public_projects.call_args.kwargs["page_size"] == 24


@pytest.mark.parametrize("locale", ["zh-CN", "en"])
def test_public_preview_never_sends_full_or_alternate_bodies(client_and_data, locale):
    client, _, briefings = client_and_data
    response = client.get("/api/report/preview", params={"date": "2026-10-09", "locale": locale})
    assert response.status_code == 200
    body = response.json()
    assert body["is_preview"] is True
    assert "Members-only details" not in body["content"]
    assert len(body["content"]) <= 1203
    assert "content_zh" not in body and "content_en" not in body
    assert "Members-only details" in briefings.get_briefing_by_date.return_value["content"]
    assert ("English issue" in body["content"]) == (locale == "en")


@pytest.mark.parametrize("content", ["x", "short issue", "long " * 1000])
def test_preview_is_bounded_even_without_paragraphs(content):
    assert content not in briefing_preview(content)
    assert len(briefing_preview(content)) <= 1203


@pytest.mark.parametrize("path", ["/api/report/latest", "/api/report/42"])
def test_member_gets_full_report_without_shared_caching(client_and_data, path):
    client, _, briefings = client_and_data
    sign_in(client)
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["content"] == briefings.get_briefing_by_date.return_value["content"]
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Authorization"


def test_authenticated_search_and_pagination_keep_their_parameters(client_and_data):
    from types import SimpleNamespace

    client, catalog, _ = client_and_data
    sign_in(client)
    catalog.min_stars = 500
    catalog.list_public_projects.return_value = SimpleNamespace(
        result={"items": [], "total": 100, "page": 2, "page_size": 60},
        effective_sort="relevance",
    )
    response = client.get("/api/projects?q=agent&page=2&page_size=60")
    assert response.status_code == 200
    assert catalog.list_public_projects.call_args.kwargs["q"] == "agent"
    assert catalog.list_public_projects.call_args.kwargs["page"] == 2
    assert catalog.list_public_projects.call_args.kwargs["page_size"] == 60


@pytest.mark.parametrize("record", [None, {"disabled": True}, {"pwd_ver": 2}])
@pytest.mark.parametrize("path", ["/api/projects?q=agent", "/api/report/latest", "/api/search?q=agent"])
def test_revoked_sessions_cannot_unlock_content(client_and_data, record, path):
    client, catalog, briefings = client_and_data
    users = sign_in(client)
    users.get_user_by_id.return_value = record
    assert client.get(path).status_code == 401
    users.get_user_by_id.assert_called_once_with(7)
    catalog.list_public_projects.assert_not_called()
    briefings.get_briefing_by_date.assert_not_called()


def test_missing_preview_preserves_not_found(client_and_data):
    client, _, briefings = client_and_data
    briefings.get_briefing_by_date.return_value = None
    assert client.get("/api/report/preview").status_code == 404


@pytest.mark.parametrize("source", ["all", "news"])
@pytest.mark.parametrize("locale", ["zh-CN", "en", "en-US"])
def test_published_public_sources_send_the_same_full_body_to_guests_bots_and_members(
    client_and_data, source, locale, monkeypatch
):
    client, _, briefings = client_and_data
    monkeypatch.setattr(routes_report, "today_cst", lambda: "2026-10-20")
    record = briefings.get_briefing_by_date.return_value
    record["subscriber_email"] = "private@example.com"
    params = {"source": source, "date": "2026-10-09", "locale": locale}
    guest = client.get("/api/report/public", params=params)
    bot = client.get("/api/report/public", params=params, headers={"User-Agent": "Googlebot"})
    sign_in(client)
    member = client.get("/api/report/public", params=params)

    assert guest.status_code == bot.status_code == member.status_code == 200
    body = guest.json()
    assert body == bot.json() == member.json()
    assert body["content"] == record["content_en" if locale.startswith("en") else "content_zh"]
    assert len(body["content"]) > 1200
    assert body["is_preview"] is False
    assert body["source"] == source
    assert set(body) == {"id", "date", "content", "source", "cache_key", "is_preview"}
    assert guest.headers["cache-control"] == "public, max-age=300"
    assert guest.headers["x-robots-tag"] == "noindex"
    key = "2026-10-09_news" if source == "news" else "2026-10-09"
    assert all(call.args == (key,) for call in briefings.get_briefing_by_date.call_args_list)


@pytest.mark.parametrize("source", ["arxiv", "github", "producthunt", "hackernews", "x", "dailyhot", "", "unknown"])
def test_other_sources_cannot_use_public_full_text_endpoint(client_and_data, source):
    client, _, briefings = client_and_data
    assert client.get("/api/report/public", params={"source": source}).status_code == 422
    briefings.get_briefing_by_date.assert_not_called()


@pytest.mark.parametrize("date", ["2026-10-09_arxiv", "2026-10-09_0800_x", "2026-10-09_news", "2026-02-30", "invalid"])
def test_public_date_cannot_address_private_cache_keys(client_and_data, date):
    client, _, briefings = client_and_data
    assert client.get("/api/report/public", params={"date": date}).status_code == 422
    briefings.get_briefing_by_date.assert_not_called()


def test_public_default_is_current_cst_day_and_future_issues_are_not_published(client_and_data, monkeypatch):
    client, _, briefings = client_and_data
    monkeypatch.setattr(routes_report, "today_cst", lambda: "2026-10-20")
    assert client.get("/api/report/public", params={"source": "news"}).status_code == 200
    briefings.get_briefing_by_date.assert_called_once_with("2026-10-20_news")
    briefings.reset_mock()
    assert client.get("/api/report/public", params={"date": "2026-10-21"}).status_code == 404
    briefings.get_briefing_by_date.assert_not_called()


@pytest.mark.parametrize("record", [None, {"content": "", "content_zh": " ", "content_en": ""}])
def test_unpublished_public_issue_returns_not_found(client_and_data, record):
    client, _, briefings = client_and_data
    briefings.get_briefing_by_date.return_value = record
    assert client.get("/api/report/public", params={"date": "2026-10-09"}).status_code == 404
