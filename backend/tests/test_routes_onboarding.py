from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import get_user_account_repository
from backend.app.api.routes_onboarding import router
from backend.app.core.auth import RequireUser, create_access_token
from backend.app.core.config import settings
from backend.app.repositories.postgres_user_account_repository import PostgresUserAccountRepository
from backend.tests.postgres_test_safety import postgres_test_sandbox


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    repo = MagicMock()
    repo.get_onboarding_status.return_value = "unseen"
    repo.save_onboarding_status.return_value = "skipped"
    app.dependency_overrides[get_user_account_repository] = lambda: repo
    app.dependency_overrides[RequireUser] = lambda: {"user_id": 7}
    return TestClient(app), app, repo


def test_state_and_updates_are_private_and_scoped_to_current_account(api):
    client, _, repo = api
    response = client.get("/api/auth/me/onboarding?user_id=99")
    assert response.json() == {"status": "unseen"}
    assert response.headers["cache-control"] == "no-store"
    repo.get_onboarding_status.assert_called_once_with(user_id=7)
    response = client.put("/api/auth/me/onboarding", json={"status": "skipped"})
    assert response.json() == {"status": "skipped"}
    assert response.headers["cache-control"] == "no-store"
    repo.save_onboarding_status.assert_called_once_with(user_id=7, status="skipped")


@pytest.mark.parametrize("body", [{}, {"status": "unseen"}, {"status": "bad"}, {"status": "completed", "user_id": 99}])
def test_rejects_invalid_status_reset_and_owner_injection(api, body):
    client, _, repo = api
    assert client.put("/api/auth/me/onboarding", json=body).status_code == 422
    repo.save_onboarding_status.assert_not_called()


def test_requires_authentication_for_both_operations(api):
    client, app, repo = api
    del app.dependency_overrides[RequireUser]
    assert client.get("/api/auth/me/onboarding").status_code == 401
    assert client.put("/api/auth/me/onboarding", json={"status": "completed"}).status_code == 401
    repo.save_onboarding_status.assert_not_called()


def test_disappearing_or_disabled_account_is_not_success(api):
    client, _, repo = api
    repo.get_onboarding_status.return_value = None
    repo.save_onboarding_status.return_value = None
    assert client.get("/api/auth/me/onboarding").status_code == 401
    assert client.put("/api/auth/me/onboarding", json={"status": "completed"}).status_code == 401


def test_migrated_postgres_jwt_isolation_and_cross_device_roundtrip(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "onboarding-test-only-secret-not-for-production")
    with postgres_test_sandbox() as sandbox:
        repo = PostgresUserAccountRepository(sandbox.database)
        owner = repo.create_user_with_email("tour@example.com", "hash")
        other = repo.create_user_with_email("other-tour@example.com", "hash")
        app = FastAPI()
        app.state.application_repositories = SimpleNamespace(users=repo)
        app.include_router(router, prefix="/api")
        app.dependency_overrides[get_user_account_repository] = lambda: repo
        token = create_access_token({"user_id": owner, "pwd_ver": repo.get_user_by_id(owner)["pwd_ver"]})
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app) as first, TestClient(app) as second:
            assert first.get("/api/auth/me/onboarding", headers=headers).json() == {"status": "unseen"}
            assert first.put("/api/auth/me/onboarding", headers=headers, json={"status": "skipped"}).json() == {"status": "skipped"}
            assert second.get("/api/auth/me/onboarding", headers=headers).json() == {"status": "skipped"}
            assert second.put("/api/auth/me/onboarding", headers=headers, json={"status": "completed"}).json() == {"status": "completed"}
            assert first.put("/api/auth/me/onboarding", headers=headers, json={"status": "skipped"}).json() == {"status": "completed"}
            assert repo.get_onboarding_status(user_id=other) == "unseen"
            # Repeated or concurrent terminal writes cannot reopen the tour.
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda s: repo.save_onboarding_status(user_id=owner, status=s), ["skipped", "completed"] * 6))
            assert repo.get_onboarding_status(user_id=owner) == "completed"
            with pytest.raises(ValueError):
                repo.save_onboarding_status(user_id=owner, status="unseen")
            from psycopg.errors import CheckViolation
            with pytest.raises(CheckViolation):
                with sandbox.database.transaction() as connection:
                    connection.execute("UPDATE users SET onboarding_status = 'invalid' WHERE id = %s", (owner,))
            with sandbox.database.transaction() as connection:
                connection.execute("UPDATE users SET disabled = TRUE WHERE id = %s", (owner,))
            assert second.get("/api/auth/me/onboarding", headers=headers).status_code == 401
            assert second.put("/api/auth/me/onboarding", headers=headers, json={"status": "completed"}).status_code == 401
            assert repo.save_onboarding_status(user_id=owner, status="skipped") is None
