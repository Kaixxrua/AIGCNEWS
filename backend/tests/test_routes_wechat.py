from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.api.routes_wechat import router
from backend.app.core.auth import RequireAdmin
from backend.app.main import app

app.include_router(router, prefix="/api", tags=["WeChat"])


def _client(identity: dict | None = None, *, login_service=None, account_service=None, sync_service=None) -> TestClient:
    overrides = {
        RequireAdmin: lambda: identity or {"role": "admin", "user_id": 1},
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

    app.dependency_overrides.update(overrides)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup_overrides():
    yield
    app.dependency_overrides.clear()


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
