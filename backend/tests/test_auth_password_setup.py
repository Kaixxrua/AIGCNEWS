from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_auth
from backend.app.api.dependencies import get_oauth_identity_repository, get_user_account_repository
from backend.app.core.auth import create_access_token
from backend.app.core.config import settings
from backend.app.repositories.postgres_oauth_identity_repository import PostgresOAuthIdentityRepository
from backend.app.repositories.postgres_user_account_repository import PostgresUserAccountRepository
from backend.app.services.email.otp_store import otp_keys
from backend.app.services.email_service import OtpDeliveryUnavailableError, OtpSendRateLimitedError
from backend.tests.postgres_test_safety import postgres_test_sandbox

EMAIL = "reader@example.com"
BODY = {"email": EMAIL, "email_code": "123456", "new_password": "new-oauth-password"}
SETUP = "/api/auth/me/password-setup"


@pytest.fixture
def account(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "isolated-password-setup-test-key")
    with postgres_test_sandbox() as sandbox:
        users = PostgresUserAccountRepository(sandbox.database)
        identities = PostgresOAuthIdentityRepository(sandbox.database)
        user = identities.resolve_first_login(provider="linuxdo", provider_subject="123", username="Reader").user
        user_id = user["id"]
        otp = SimpleNamespace(send_otp=AsyncMock(), verify_otp=AsyncMock(return_value=True), consume_otp=AsyncMock())
        monkeypatch.setattr(routes_auth, "_get_email_service", lambda _request: otp)
        app = FastAPI()
        app.state.application_repositories = SimpleNamespace(users=users)
        app.include_router(routes_auth.router, prefix="/api")
        app.dependency_overrides[get_user_account_repository] = lambda: users
        app.dependency_overrides[get_oauth_identity_repository] = lambda: identities
        token = create_access_token({"user_id": user_id, "pwd_ver": user["pwd_ver"]})
        with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
            yield SimpleNamespace(client=client, users=users, identities=identities, otp=otp,
                                  database=sandbox.database, user_id=user_id)


@pytest.mark.parametrize("existing_email", [None, EMAIL])
def test_oauth_password_setup_enables_login_preserves_identity_and_revokes_old_session(account, existing_email):
    if existing_email:
        with account.database.transaction() as connection:
            connection.execute("UPDATE users SET email = %s, email_verified = TRUE WHERE id = %s",
                               (existing_email, account.user_id))
    response = account.client.post(SETUP + "/send-otp", json={"email": EMAIL})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    account.otp.send_otp.assert_awaited_once_with(EMAIL, purpose="password_setup", deliver=True)
    before = account.users.get_user_by_id(account.user_id)
    response = account.client.post(SETUP, json=BODY)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    account.otp.verify_otp.assert_awaited_once_with(EMAIL, "123456", consume=True, purpose="password_setup")
    account.otp.consume_otp.assert_not_awaited()
    updated = account.users.get_user_by_email(EMAIL)
    assert updated["password_login_enabled"] is True
    assert updated["hashed_password"] != BODY["new_password"]
    assert updated["pwd_ver"] == before["pwd_ver"] + 1
    assert account.users.get_user_count() == 1
    assert account.client.get("/api/auth/me").status_code == 401
    account.client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
    profile = account.client.get("/api/auth/me").json()
    assert profile["user_id"] == account.user_id
    assert profile["email_verified"] is True
    assert profile["password_login_enabled"] is True
    assert profile["oauth_identities"][0]["provider"] == "linuxdo"
    assert account.client.post(SETUP, json=BODY).status_code == 409
    login = account.client.post("/api/auth/login", json={"email": EMAIL, "password": BODY["new_password"]})
    assert login.status_code == 200
    account.client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
    assert account.client.get("/api/auth/me").json()["user_id"] == account.user_id
    assert account.identities.resolve_first_login(provider="linuxdo", provider_subject="123").user["id"] == account.user_id


def test_setup_rejects_invalid_otp_and_occupied_email_without_merging(account):
    other = account.users.create_user_with_email(EMAIL, "original-hash", role="admin")
    account.otp.verify_otp.return_value = False
    # Sending does not disclose the email conflict.
    assert account.client.post(SETUP + "/send-otp", json={"email": EMAIL}).status_code == 200
    assert account.client.post(SETUP, json=BODY).status_code == 400
    account.otp.verify_otp.return_value = True
    assert account.client.post(SETUP, json=BODY).status_code == 409
    assert account.users.get_user_by_email(EMAIL)["id"] == other
    assert account.users.get_user_by_email(EMAIL)["hashed_password"] == "original-hash"
    assert account.users.get_user_by_id(account.user_id)["password_login_enabled"] is False
    assert account.identities.get_by_provider_subject("linuxdo", "123")["user_id"] == account.user_id
    account.otp.consume_otp.assert_not_awaited()


@pytest.mark.parametrize("mutation", [
    "email = 'other@example.com'", "disabled = TRUE", "password_login_enabled = TRUE",
])
def test_setup_rejects_email_replacement_disabled_and_password_accounts(account, mutation):
    with account.database.transaction() as connection:
        connection.execute(f"UPDATE users SET {mutation} WHERE id = %s", (account.user_id,))
    expected = 401 if mutation == "disabled = TRUE" else 409
    assert account.client.post(SETUP + "/send-otp", json={"email": EMAIL}).status_code == expected
    assert account.client.post(SETUP, json=BODY).status_code == expected
    account.otp.send_otp.assert_not_awaited()
    account.otp.verify_otp.assert_not_awaited()


@pytest.mark.parametrize("extra", [{"user_id": 999}, {"email_code": "oops"}, {"new_password": "12345678"}])
def test_setup_rejects_target_injection_and_invalid_input(account, extra):
    assert account.client.post(SETUP, json=BODY | extra).status_code == 422
    account.otp.verify_otp.assert_not_awaited()


def test_setup_requires_authentication_and_handles_otp_delivery_failures(account):
    for failure, status in [(OtpSendRateLimitedError("wait"), 429), (OtpDeliveryUnavailableError("unavailable"), 503)]:
        account.otp.send_otp.side_effect = failure
        assert account.client.post(SETUP + "/send-otp", json={"email": EMAIL}).status_code == status
    account.client.headers.pop("Authorization")
    assert account.client.post(SETUP, json=BODY).status_code == 401
    assert account.client.post(SETUP + "/send-otp", json={"email": EMAIL}).status_code == 401


@pytest.mark.parametrize("race", ["email", "version", "disabled", "password", "owner"])
def test_setup_atomic_update_rejects_changed_account_or_concurrent_email_owner(account, monkeypatch, race):
    original = account.users.enable_password_login

    def update(**kwargs):
        with account.database.transaction() as connection:
            if race == "owner":
                account.users.create_user_with_email(EMAIL, "other-hash")
            else:
                assignment = {
                    "email": "email = 'changed@example.com'", "version": "pwd_ver = pwd_ver + 1",
                    "disabled": "disabled = TRUE", "password": "password_login_enabled = TRUE",
                }[race]
                connection.execute(f"UPDATE users SET {assignment} WHERE id = %s", (account.user_id,))
        return original(**kwargs)

    monkeypatch.setattr(account.users, "enable_password_login", update)
    response = account.client.post(SETUP, json=BODY)
    assert response.status_code == 409
    account.otp.consume_otp.assert_not_awaited()
    assert account.users.get_user_by_id(account.user_id)["email"] != EMAIL


def test_setup_otp_has_separate_keys_for_all_other_auth_actions():
    setup_keys = set(otp_keys(EMAIL, "password_setup"))
    assert len(setup_keys) == 3
    for purpose in ["registration", "password_change", "password_reset", "email_change"]:
        assert setup_keys.isdisjoint(otp_keys(EMAIL, purpose))


def test_setup_endpoints_apply_rate_limits(monkeypatch):
    from backend.app.core.auth import RequireUser
    app = FastAPI()
    app.include_router(routes_auth.router, prefix="/api")
    app.dependency_overrides[RequireUser] = lambda: {"user_id": 7}
    app.dependency_overrides[get_user_account_repository] = lambda: Mock()
    limiter = AsyncMock(side_effect=routes_auth.HTTPException(429, "limited"))
    monkeypatch.setattr(routes_auth, "_enforce_rate_limit", limiter)
    with TestClient(app) as client:
        assert client.post(SETUP + "/send-otp", json={"email": EMAIL}).status_code == 429
        assert client.post(SETUP, json=BODY).status_code == 429
    assert [call.kwargs["action"] for call in limiter.await_args_list] == [
        "auth.password_setup_otp", "auth.password_setup",
    ]
