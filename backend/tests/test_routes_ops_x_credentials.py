from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_ops
from backend.app.api.dependencies import (
    get_x_credential_repository,
    get_x_watch_account_repository,
)
from backend.app.core.auth import RequireAdmin
from backend.app.repositories.x_credentials_repository import XCredentialRepository
from backend.app.repositories.x_watch_repository import XWatchAccountRepository

RAW_AUTH_TOKEN = "raw-auth-token-secret"
RAW_CT0 = "raw-ct0-token-secret"


def _row(**overrides):
    row = {
        "id": 7,
        "display_name": "Primary X",
        "note": "main cookie pair",
        "auth_token": RAW_AUTH_TOKEN,
        "ct0": RAW_CT0,
        "enabled": True,
        "sort_order": 0,
        "last_test_status": "unknown",
        "last_test_message": "",
        "last_test_at": None,
        "created_at": None,
        "updated_at": None,
    }
    row.update(overrides)
    return row


def _payload(**overrides):
    payload = {
        "display_name": "Primary X",
        "note": "main cookie pair",
        "enabled": True,
        "sort_order": 0,
        "auth_token": RAW_AUTH_TOKEN,
        "ct0": RAW_CT0,
    }
    payload.update(overrides)
    return payload


def _client(
    credentials: XCredentialRepository,
    watch: XWatchAccountRepository | None = None,
    *,
    admin: bool = True,
) -> TestClient:
    app = FastAPI()
    app.include_router(routes_ops.router, prefix="/api")
    if admin:
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
    app.dependency_overrides[get_x_credential_repository] = lambda: credentials
    app.dependency_overrides[get_x_watch_account_repository] = lambda: watch or MagicMock(
        spec=XWatchAccountRepository
    )
    return TestClient(app)


def assert_secrets_absent(response) -> None:
    body = response.text
    assert RAW_AUTH_TOKEN not in body
    assert RAW_CT0 not in body
    assert "auth_token\"" not in body
    assert "ct0\"" not in body


def test_list_create_and_update_return_only_safe_secret_projection() -> None:
    repository = MagicMock(spec=XCredentialRepository)
    repository.list_x_credentials.return_value = [_row()]
    repository.create_x_credential.return_value = _row()
    repository.update_x_credential.return_value = _row(display_name="Backup X")
    client = _client(repository)

    listed = client.get("/api/ops/x-credentials")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["auth_token_masked"] == "raw-****cret"
    assert listed.json()["items"][0]["ct0_masked"] == "raw-****cret"
    assert_secrets_absent(listed)

    created = client.post("/api/ops/x-credentials", json=_payload())
    assert created.status_code == 200
    assert created.json()["auth_token_configured"] is True
    assert_secrets_absent(created)

    updated = client.put(
        "/api/ops/x-credentials/7",
        json=_payload(display_name="Backup X", auth_token=None, ct0=None),
    )
    assert updated.status_code == 200
    update_payload = repository.update_x_credential.call_args.args[1]
    assert update_payload["auth_token"] is None
    assert update_payload["ct0"] is None
    assert_secrets_absent(updated)


def test_create_and_update_reject_incomplete_secret_pairs() -> None:
    repository = MagicMock(spec=XCredentialRepository)
    client = _client(repository)

    created = client.post(
        "/api/ops/x-credentials",
        json=_payload(ct0=None),
    )
    assert created.status_code == 400
    repository.create_x_credential.assert_not_called()

    updated = client.put(
        "/api/ops/x-credentials/7",
        json=_payload(auth_token="replacement", ct0=None),
    )
    assert updated.status_code == 400
    repository.update_x_credential.assert_not_called()


def test_delete_and_test_map_missing_rows_to_404() -> None:
    repository = MagicMock(spec=XCredentialRepository)
    repository.delete_x_credential.return_value = False
    repository.get_x_credential.return_value = None
    watch = MagicMock(spec=XWatchAccountRepository)
    watch.list_enabled_x_handles.return_value = ["openai"]
    client = _client(repository, watch)

    assert client.delete("/api/ops/x-credentials/99").status_code == 404
    assert client.post("/api/ops/x-credentials/99/test").status_code == 404


def test_test_endpoint_uses_selected_row_and_first_enabled_handle() -> None:
    repository = MagicMock(spec=XCredentialRepository)
    repository.get_x_credential.return_value = _row()
    repository.update_x_credential_test_result.return_value = _row(
        last_test_status="failed",
        last_test_message="x_auth_expired",
    )
    watch = MagicMock(spec=XWatchAccountRepository)
    watch.list_enabled_x_handles.return_value = ["openai", "karpathy"]
    client = _client(repository, watch)

    from unittest.mock import patch

    with patch(
        "backend.app.services.x_credentials.probe.probe_x_credential",
        return_value={"status": "failed", "message": "x_auth_expired"},
    ) as probe:
        response = client.post("/api/ops/x-credentials/7/test")

    assert response.status_code == 200
    assert response.json()["message"] == "x_auth_expired"
    probe.assert_called_once()
    assert probe.call_args.args[0]["id"] == 7
    assert probe.call_args.args[1] == "openai"
    assert_secrets_absent(response)


def test_routes_require_admin_before_repository_calls() -> None:
    repository = MagicMock(spec=XCredentialRepository)
    response = _client(repository, admin=False).get("/api/ops/x-credentials")

    assert response.status_code in (401, 403)
    repository.list_x_credentials.assert_not_called()
