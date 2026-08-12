from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.api.dependencies import get_wechat_follow_service
from backend.app.api.routes_wechat import router
from backend.app.core.auth import RequireAdmin, RequireUser
from backend.app.main import app
from backend.app.services.source_plugins.wechat_source import WeChatError


def _wechat_account_not_found() -> WeChatError:
    """与私有实现 WeChatAccountNotFound 等价的契约层错误（路由只读 code/message）。"""
    return WeChatError("WECHAT_ACCOUNT_NOT_FOUND", "公众号不存在")

app.include_router(router, prefix="/api", tags=["WeChat"])


def _client(identity: dict | None = None, *, login_service=None, account_service=None, sync_service=None, follow_service=None) -> TestClient:
    overrides = {
        RequireAdmin: lambda: identity or {"role": "admin", "user_id": 1},
        RequireUser: lambda: identity or {"role": "user", "user_id": 1},
    }
    if login_service is not None:
        from backend.app.api.dependencies import get_wechat_login_service
        overrides[get_wechat_login_service] = lambda: login_service
    if account_service is not None:
        from backend.app.api.dependencies import get_wechat_account_service
        overrides[get_wechat_account_service] = lambda: account_service
    if sync_service is not None:
        from backend.app.api.dependencies import get_wechat_sync_service
        overrides[get_wechat_sync_service] = lambda: sync_service
    if follow_service is not None:
        from backend.app.api.dependencies import get_wechat_follow_service
        overrides[get_wechat_follow_service] = lambda: follow_service

    app.dependency_overrides.update(overrides)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _wechat_source_enabled(monkeypatch):
    """既有用例默认开关开启；关态降级由专门用例覆盖。"""
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "wechat_source_enabled", True)


def test_wechat_routes_404_when_source_disabled(monkeypatch) -> None:
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "wechat_source_enabled", False)
    client = _client()
    response = client.get("/api/ops/wechat/session")
    assert response.status_code == 404
    assert response.json()["detail"] == "wechat_source_disabled"


def test_create_login_session_returns_attempt() -> None:
    service = MagicMock()
    service.start_login_attempt = AsyncMock(
        return_value={
            "attempt_id": uuid4(),
            "status": "waiting_scan",
            "expires_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    client = _client(login_service=service)
    response = client.post("/api/ops/wechat/login-sessions")
    assert response.status_code == 200
    assert response.json()["status"] == "waiting_scan"
    service.start_login_attempt.assert_called_once_with(1)


def test_get_session_hides_secrets() -> None:
    service = MagicMock()
    service.get_session_summary = AsyncMock(
        return_value={
            "connected": True,
            "status": "active",
            "account_name": "Test",
            "account_avatar_url": "",
            "last_validated_at": None,
            "last_used_at": None,
            "expires_at": None,
            "invalid_reason_code": None,
        }
    )
    client = _client(login_service=service)
    response = client.get("/api/ops/wechat/session")
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is True
    assert "token" not in data
    assert "cookie" not in data


def test_search_accounts_requires_query() -> None:
    service = MagicMock()
    client = _client(account_service=service)
    response = client.get("/api/ops/wechat/accounts/search")
    assert response.status_code == 422


def test_sync_account_submits_background_task() -> None:
    service = MagicMock()
    service.submit_sync = AsyncMock(
        return_value={"status": "submitted", "account_id": 42, "message": "queued"}
    )
    client = _client(sync_service=service)
    response = client.post("/api/ops/wechat/accounts/42/sync")
    assert response.status_code == 200
    assert response.json()["status"] == "submitted"
    service.submit_sync.assert_called_once_with(1, 42)


def test_unauthenticated_request_rejected() -> None:
    client = TestClient(app)
    response = client.get("/api/ops/wechat/session")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# User-facing catalog / follow / feed
# ---------------------------------------------------------------------------


def _catalog_item(account_id: int, *, followed: bool) -> dict:
    return {
        "id": account_id,
        "nickname": f"公众号{account_id}",
        "alias": "",
        "avatar_url": "",
        "signature": "",
        "sort_order": 0,
        "followed": followed,
    }


def test_catalog_returns_items_with_follow_state() -> None:
    service = MagicMock()
    service.list_catalog.return_value = [
        _catalog_item(7, followed=True),
        _catalog_item(8, followed=False),
    ]
    client = _client(follow_service=service)
    response = client.get("/api/ops/wechat/catalog")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert [item["followed"] for item in data["items"]] == [True, False]
    assert "fakeid" not in data["items"][0]
    assert "owner_id" not in data["items"][0]
    service.list_catalog.assert_called_once_with(1)


def test_follow_account_is_idempotent() -> None:
    service = MagicMock()
    service.follow.return_value = {"account_id": 7, "followed": True}
    client = _client(follow_service=service)
    for _ in range(2):
        response = client.post("/api/ops/wechat/accounts/7/follow")
        assert response.status_code == 200
        assert response.json() == {"account_id": 7, "followed": True}
    service.follow.assert_called_with(1, 7)


def test_follow_missing_or_disabled_account_returns_404() -> None:
    service = MagicMock()
    service.follow.side_effect = _wechat_account_not_found()
    client = _client(follow_service=service)
    response = client.post("/api/ops/wechat/accounts/999/follow")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "WECHAT_ACCOUNT_NOT_FOUND"


def test_unfollow_account_is_idempotent() -> None:
    service = MagicMock()
    service.unfollow.return_value = {"account_id": 7, "followed": False}
    client = _client(follow_service=service)
    for _ in range(2):
        response = client.delete("/api/ops/wechat/accounts/7/follow")
        assert response.status_code == 200
        assert response.json() == {"account_id": 7, "followed": False}


def test_feed_groups_articles_by_account() -> None:
    service = MagicMock()
    service.get_feed.return_value = [
        {
            "account": _catalog_item(7, followed=True),
            "articles": [
                {
                    "id": 11,
                    "account_id": 7,
                    "stable_article_key": "k1",
                    "title": "文章A",
                    "published_at": None,
                },
                {
                    "id": 12,
                    "account_id": 7,
                    "stable_article_key": "k2",
                    "title": "文章B",
                    "published_at": None,
                },
            ],
        },
        {
            "account": _catalog_item(8, followed=True),
            "articles": [],
        },
    ]
    client = _client(follow_service=service)
    response = client.get("/api/ops/wechat/feed")
    assert response.status_code == 200
    data = response.json()
    assert data["per_account"] == 5
    assert len(data["items"]) == 2
    assert [a["title"] for a in data["items"][0]["articles"]] == ["文章A", "文章B"]
    assert data["items"][1]["articles"] == []
    service.get_feed.assert_called_once_with(1, per_account=5)


def test_feed_rejects_out_of_range_per_account() -> None:
    client = _client(follow_service=MagicMock())
    assert client.get("/api/ops/wechat/feed?per_account=0").status_code == 422
    assert client.get("/api/ops/wechat/feed?per_account=11").status_code == 422


def test_article_detail_returns_full_body() -> None:
    service = MagicMock()
    service.get_article_detail.return_value = {
        "id": 11,
        "account_id": 7,
        "stable_article_key": "2247483765-1",
        "title": "文章A",
        "has_content": True,
        "content_html": "<p>正文</p>",
        "content_fetched_at": "2026-08-06T07:44:00+00:00",
        "published_at": None,
    }
    client = _client(follow_service=service)
    response = client.get("/api/ops/wechat/accounts/7/articles/11")
    assert response.status_code == 200
    data = response.json()
    assert data["content_html"] == "<p>正文</p>"
    assert data["has_content"] is True
    assert data["content_fetched_at"] == "2026-08-06T07:44:00Z"
    service.get_article_detail.assert_called_once_with(1, 7, 11)


def test_article_detail_not_followed_returns_404() -> None:
    service = MagicMock()
    service.get_article_detail.side_effect = _wechat_account_not_found()
    client = _client(follow_service=service)
    response = client.get("/api/ops/wechat/accounts/999/articles/11")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "WECHAT_ACCOUNT_NOT_FOUND"


def test_article_detail_rejects_non_admin_user() -> None:
    """全文详情收敛为管理员自用：普通注册用户 403（展示层仅摘要+原文链接）。"""
    service = MagicMock()
    # 只覆盖 RequireUser、保留真实 RequireAdmin，让角色检查真实生效
    app.dependency_overrides.update(
        {
            RequireUser: lambda: {"role": "user", "user_id": 2},
            get_wechat_follow_service: lambda: service,
        }
    )
    client = TestClient(app)
    response = client.get("/api/ops/wechat/accounts/7/articles/11")
    assert response.status_code == 403
    service.get_article_detail.assert_not_called()


def test_feed_response_strips_full_text_fields() -> None:
    """契约：feed/list 面向全部注册用户，响应不得携带全文与抓取时间字段。"""
    service = MagicMock()
    service.get_feed.return_value = [
        {
            "account": _catalog_item(7, followed=True),
            "articles": [
                {
                    "id": 11,
                    "account_id": 7,
                    "stable_article_key": "k1",
                    "title": "文章A",
                    "has_content": True,
                    "content_html": "<p>正文不应外泄</p>",
                    "content_fetched_at": "2026-08-06T07:44:00+00:00",
                    "published_at": None,
                },
            ],
        },
    ]
    client = _client(follow_service=service)
    response = client.get("/api/ops/wechat/feed")
    assert response.status_code == 200
    article = response.json()["items"][0]["articles"][0]
    assert "content_html" not in article
    assert "content_fetched_at" not in article


def test_article_detail_rejects_unauthenticated() -> None:
    client = TestClient(app)
    assert client.get("/api/ops/wechat/accounts/7/articles/11").status_code == 401


def test_user_endpoints_reject_unauthenticated() -> None:
    client = TestClient(app)
    assert client.get("/api/ops/wechat/catalog").status_code == 401
    assert client.post("/api/ops/wechat/accounts/7/follow").status_code == 401
    assert client.delete("/api/ops/wechat/accounts/7/follow").status_code == 401
    assert client.get("/api/ops/wechat/feed").status_code == 401
