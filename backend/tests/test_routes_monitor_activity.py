from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_monitor_activity as routes
from backend.app.core.auth import RequireUser


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    repo = MagicMock()
    repo.record.return_value = {"day": "2026-10-10", "recorded": True}
    repo.stats.return_value = {"days": []}
    repo.read.return_value = {"stale": True}
    app.dependency_overrides[routes.account_visits] = lambda: repo
    app.dependency_overrides[routes.email_monitor] = lambda: repo
    return TestClient(app), repo


def login(client, role="user"):
    client.app.dependency_overrides[RequireUser] = lambda: {"user_id": 47, "role": role}


def test_anonymous_cannot_write_account_activity_or_read_monitoring(client):
    http, repo = client
    assert http.post("/api/dashboard/account-visit").status_code == 401
    for path in ("/api/monitor/email", "/api/monitor/user-return-visits"):
        assert http.get(path).status_code == 401
    repo.record.assert_not_called()
    repo.stats.assert_not_called()
    repo.read.assert_not_called()


def test_only_verified_identity_controls_visit_even_with_forged_body(client):
    http, repo = client
    login(http)
    response = http.post("/api/dashboard/account-visit", json={"user_id": 999, "day": "2020-01-01"})
    assert response.status_code == 200
    assert response.json()["user_id"] == 47
    assert response.headers["cache-control"] == "no-store"
    repo.record.assert_called_once_with(47)
    assert http.get("/api/monitor/email").status_code == 403
    assert http.get("/api/monitor/user-return-visits").status_code == 403


def test_recognized_automation_does_not_count_as_web_visitor(client):
    http, repo = client
    login(http)
    response = http.post("/api/dashboard/account-visit", headers={"User-Agent": "Googlebot"})
    assert response.json() == {"recorded": False}
    repo.record.assert_not_called()


def test_admin_reads_are_not_cached_and_cannot_trigger_sends(client):
    http, repo = client
    login(http, "admin")
    repo.stats.return_value = {"days": [{
        "day": "2026-10-12", "coverage": "complete", "total_visitors": 453,
        "active_users": 105, "returning_users": 9, "new_users": 96,
        "return_rate": 9 / 357, "registration_rate": 96 / 444,
    }]}
    repo.stats.return_value["visitor_returns"] = {
        "timezone": "Asia/Shanghai", "tracking_started_at": "2026-10-10T00:00:00+08:00",
        "as_of": "2026-10-12T10:00:00+08:00",
        "days": [{"day": "2026-10-12", "coverage": "partial", "total_visitors": 453,
                  "returning_visitors": 100, "return_rate": 100 / 453}],
    }
    assert http.get("/api/monitor/email").headers["cache-control"] == "no-store"
    response = http.get("/api/monitor/user-return-visits?days=7")
    assert response.status_code == 200
    assert response.json() == repo.stats.return_value
    assert response.headers["cache-control"] == "no-store"
    repo.stats.assert_called_once_with(7)
    assert http.get("/api/monitor/user-return-visits?days=1000").status_code == 422
    repo.claim.assert_not_called()
