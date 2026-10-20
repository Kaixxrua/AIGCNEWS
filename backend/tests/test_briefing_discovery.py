from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_report
from backend.app.api.dependencies import get_briefing_repository, get_document_repository
from backend.app.api.routes_sitemap import _iso_date, router
from backend.app.repositories.briefing_repository import BriefingReader
from backend.app.repositories.postgres_briefing_repository import PostgresBriefingRepository
from backend.app.services.briefing.discovery import briefing_index


def issue(key, *, zh=True, en=True, modified="2026-10-19T08:15:00+08:00"):
    return {"date": key, "has_zh": zh, "has_en": en, "created_at": modified}


@pytest.fixture
def repository():
    repo = MagicMock(spec=BriefingReader)
    repo.list_briefing_index.return_value = [
        issue("2026-10-19_news"), issue("2026-10-17_news", en=False),
        issue("2026-10-15_news"), issue("2026-10-13_news"),
        issue("2026-10-19"), issue("2026-10-17_github"),
    ]
    return repo


@pytest.fixture
def client(repository):
    app = FastAPI()
    # Match production registration order; the numeric report detail route must
    # not shadow public archive navigation.
    app.include_router(routes_report.router, prefix="/api")
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_briefing_repository] = lambda: repository
    documents = MagicMock()
    documents.list_recent_by_source.return_value = [{"id": "paper-id"}]
    app.dependency_overrides[get_document_repository] = lambda: documents
    with patch("backend.app.api.routes_sitemap.today_cst", return_value="2026-10-20"):
        with TestClient(app) as test_client:
            yield test_client


def test_index_only_contains_real_nonempty_issue_keys_in_the_window(repository):
    repository.list_briefing_index.return_value += [
        issue("2026-10-19_news"),  # repeated identities must not multiply URLs
        issue("2026-10-20_news", zh=False, en=False),
        issue("2026-10-21_news"), issue("2026-01-01_news"),
        issue("2026-02-31_news"), issue("20261019_news"),
        issue("2026-10-18_unknown"), issue("2026-10-18_all"),
        issue("2026-10-18_0800_x"), issue("2026-10-18_dailyhot"),
        issue("2026-10-18_news&admin=true"), issue(""),
    ]
    result = briefing_index(repository, date(2026, 10, 20))
    assert len(result) == 6
    assert result[0]["date"] == "2026-10-19"
    repository.list_briefing_index.assert_called_once_with(since="2026-07-22", until="2026-10-20")
    assert next(row for row in result if row["date"] == "2026-10-17" and row["source"] == "news")["locales"] == ["zh-CN"]


def test_sitemap_keeps_papers_and_adds_escaped_published_issue_urls(client):
    response = client.get("/api/sitemap.xml")
    assert response.status_code == 200
    root = ElementTree.fromstring(response.content)
    urls = [node.text for node in root.findall(".//{*}loc")]
    assert any(url.endswith("/papers/paper-id/read") for url in urls)
    assert any(url.endswith("/report?date=2026-10-19&type=news&lang=en-US") for url in urls)
    assert any(url.endswith("/report?date=2026-10-19&lang=zh-CN") for url in urls)
    assert not any("2026-10-17&type=news&lang=en-US" in url for url in urls)
    assert len(urls) == len(set(urls)) == 18
    assert "<lastmod>2026-10-19</lastmod>" in response.text
    assert response.headers["cache-control"] == "public, max-age=3600"


def test_archive_links_to_neighbouring_published_dates_and_never_exposes_content(client, repository):
    repository.list_briefing_index.return_value[0].update(content="PRIVATE FULL BODY", email="private@example.test")
    response = client.get("/api/report/archive", params={"source": "news", "date": "2026-10-17", "limit": 3})
    assert response.status_code == 200
    assert response.json() == {"items": [
        {"date": day, "source": "news", "url": f"/report?date={day}&type=news&lang=zh-CN"}
        for day in ("2026-10-19", "2026-10-15", "2026-10-13")
    ]}
    assert response.headers["cache-control"] == "public, max-age=300"
    assert response.headers["x-robots-tag"] == "noindex"
    assert "PRIVATE" not in response.text and "email" not in response.text


def test_archive_filters_languages_sources_and_clamps_future_anchors(client):
    result = client.get("/api/report/archive", params={"source": "news", "locale": "en-US", "date": "2099-01-01", "limit": 2}).json()
    assert [row["date"] for row in result["items"]] == ["2026-10-19", "2026-10-15"]
    assert all(row["url"].endswith("lang=en-US") for row in result["items"])
    assert client.get("/api/report/archive", params={"source": "arxiv"}).json() == {"items": []}


@pytest.mark.parametrize("params", [{"date": "2026-02-31"}, {"source": "private"}, {"locale": "bad"}, {"limit": 10000}])
def test_archive_rejects_invalid_or_unbounded_queries(client, params):
    assert client.get("/api/report/archive", params=params).status_code == 422


def test_repository_bounds_query_and_only_projects_metadata():
    database = MagicMock()
    cursor = database.transaction.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [issue("2026-10-19_news")]
    repo = PostgresBriefingRepository(database)
    assert repo.list_briefing_index(since="2026-07-22", until="2026-10-20", limit=99999) == cursor.fetchall.return_value
    sql, params = cursor.execute.call_args.args
    assert params == ("2026-07-22", "2026-10-20", 1000)
    assert "SELECT date, created_at," in sql and "AS has_zh" in sql and "AS has_en" in sql
    assert "SELECT *" not in sql and "content_preview" not in sql


@pytest.mark.parametrize("value", ["2026-99-01", "2026-02-31", "not-a-date"])
def test_sitemap_does_not_publish_invalid_lastmod(value):
    assert _iso_date(value) is None
