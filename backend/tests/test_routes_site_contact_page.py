from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import get_site_contact_page_repository
from backend.app.api.routes_ops import router as ops_router
from backend.app.api.routes_site import router as site_router
from backend.app.core.auth import RequireAdmin
from backend.app.repositories.site_contact_page_repository import (
    SiteContactEntry,
    SiteContactPage,
    SiteContactServiceCard,
)


def _page(**overrides) -> SiteContactPage:
    values = {
        "enabled": True,
        "nav_label": "合作",
        "title": "联系合作",
        "subtitle": "外包 · 商务合作",
        "service_cards": (
            SiteContactServiceCard(title="外包开发", description="AI 应用定制", icon="code"),
        ),
        "contact_entries": (
            SiteContactEntry(label="QQ 群", value="123456", href="", qr_image_url="/qr.png"),
        ),
        "body_markdown": "# 欢迎",
        "updated_at": datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SiteContactPage(**values)


def _payload(**overrides) -> dict:
    values = {
        "enabled": True,
        "nav_label": "合作",
        "title": "联系合作",
        "subtitle": "外包 · 商务合作",
        "service_cards": [
            {"title": "外包开发", "description": "AI 应用定制", "icon": "code"},
        ],
        "contact_entries": [
            {"label": "QQ 群", "value": "123456", "href": "", "qr_image_url": "/qr.png"},
        ],
        "body_markdown": "# 欢迎",
    }
    values.update(overrides)
    return values


def _client(repository, *, admin: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(ops_router, prefix="/api")
    app.include_router(site_router, prefix="/api")
    if admin:
        app.dependency_overrides[RequireAdmin] = lambda: {
            "role": "admin",
            "email": "admin@example.test",
        }
    app.dependency_overrides[get_site_contact_page_repository] = lambda: repository
    return TestClient(app)


def test_admin_get_returns_synthesized_defaults_when_row_missing() -> None:
    repository = MagicMock()
    repository.get_site_contact_page.return_value = None

    response = _client(repository).get("/api/ops/site/contact-page")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["title"] == ""
    assert body["service_cards"] == []
    assert body["contact_entries"] == []


def test_admin_put_round_trips_saved_page() -> None:
    repository = MagicMock()
    repository.upsert_site_contact_page.return_value = _page()

    response = _client(repository).put("/api/ops/site/contact-page", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["nav_label"] == "合作"
    assert body["service_cards"][0]["title"] == "外包开发"
    assert body["contact_entries"][0]["qr_image_url"] == "/qr.png"
    repository.upsert_site_contact_page.assert_called_once()
    kwargs = repository.upsert_site_contact_page.call_args.kwargs
    assert kwargs["enabled"] is True
    assert kwargs["service_cards"][0].title == "外包开发"
    assert kwargs["contact_entries"][0].label == "QQ 群"


def test_admin_put_rejects_enabled_without_title() -> None:
    repository = MagicMock()

    response = _client(repository).put(
        "/api/ops/site/contact-page", json=_payload(title="  ")
    )

    assert response.status_code == 422
    repository.upsert_site_contact_page.assert_not_called()


def test_admin_put_rejects_invalid_href_scheme() -> None:
    repository = MagicMock()

    response = _client(repository).put(
        "/api/ops/site/contact-page",
        json=_payload(
            contact_entries=[
                {"label": "QQ 群", "value": "123", "href": "javascript:alert(1)", "qr_image_url": ""},
            ]
        ),
    )

    assert response.status_code == 422
    repository.upsert_site_contact_page.assert_not_called()


def test_admin_put_rejects_invalid_qr_url_scheme() -> None:
    repository = MagicMock()

    response = _client(repository).put(
        "/api/ops/site/contact-page",
        json=_payload(
            contact_entries=[
                {"label": "QQ 群", "value": "123", "href": "", "qr_image_url": "data:text/html,x"},
            ]
        ),
    )

    assert response.status_code == 422
    repository.upsert_site_contact_page.assert_not_called()


def test_ops_routes_require_admin() -> None:
    repository = MagicMock()
    client = _client(repository, admin=False)

    get_response = client.get("/api/ops/site/contact-page")
    put_response = client.put("/api/ops/site/contact-page", json=_payload())

    assert get_response.status_code in (401, 403)
    assert put_response.status_code in (401, 403)
    repository.get_site_contact_page.assert_not_called()
    repository.upsert_site_contact_page.assert_not_called()


def test_public_get_allows_anonymous_and_reports_disabled_when_row_missing() -> None:
    repository = MagicMock()
    repository.get_site_contact_page.return_value = None

    # 不挂任何 RequireAdmin override：公开端点必须免鉴权可达
    response = _client(repository, admin=False).get("/api/site/contact-page")

    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_public_get_hides_draft_content_when_disabled() -> None:
    repository = MagicMock()
    repository.get_site_contact_page.return_value = _page(enabled=False)

    response = _client(repository, admin=False).get("/api/site/contact-page")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    # 未启用页面的草稿内容不下发（防泄漏：标题/卡片/联系方式全部留空）
    assert body["title"] == ""
    assert body["service_cards"] == []
    assert body["contact_entries"] == []
    assert "联系合作" not in str(body)
    assert "123456" not in str(body)


def test_public_get_returns_full_content_when_enabled() -> None:
    repository = MagicMock()
    repository.get_site_contact_page.return_value = _page()

    response = _client(repository, admin=False).get("/api/site/contact-page")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["nav_label"] == "合作"
    assert body["title"] == "联系合作"
    assert body["service_cards"][0]["icon"] == "code"
    assert body["contact_entries"][0]["value"] == "123456"
    assert body["body_markdown"] == "# 欢迎"
    assert body["updated_at"] is not None
