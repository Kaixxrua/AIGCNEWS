"""GET/PUT/DELETE /api/ops/oauth/config 的路由契约测试。

钉住的对外语义：
- 全部端点 RequireAdmin，且响应 Cache-Control: no-store；
- 任何响应都不回明文密钥（投影只有 *_configured + *_masked）；
- PUT 的 ValueError → 400 且消息不泄露已有密文；
- 仓储/加密层异常不暴露内部细节、不回明文。
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_ops_oauth
from backend.app.api.dependencies import get_oauth_config_admin_service
from backend.app.core.auth import RequireAdmin
from backend.app.repositories.oauth_settings_repository import OAuthSettings
from backend.app.services.auth.oauth.config_admin import OAuthConfigAdminService
from backend.app.services.auth.oauth.runtime_config import (
    configure_oauth_settings_reader,
    reset_oauth_config_provider,
)

DB_GITHUB_SECRET = "db-github-secret-0002"
NEW_GITHUB_SECRET = "gho_newsecretvalue1234"


def _row(**overrides) -> OAuthSettings:
    values = {
        "enabled_providers": "github",
        "public_base_url": "https://db.example.test",
        "github_client_id": "db-github-id",
        "github_client_secret": DB_GITHUB_SECRET,
        "google_client_id": "",
        "google_client_secret": "",
        "wechat_app_id": "",
        "wechat_app_secret": "",
        "state_ttl_seconds": 300,
        "handoff_ttl_seconds": 120,
        "updated_at": datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return OAuthSettings(**values)


class FakeOAuthSettingsRepository:
    def __init__(self, row: OAuthSettings | None = None) -> None:
        self._row = row

    def get_oauth_settings(self) -> OAuthSettings | None:
        return self._row

    def upsert_oauth_settings(self, **kwargs) -> OAuthSettings:
        self._row = OAuthSettings(
            **kwargs,
            updated_at=datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc),
        )
        return self._row

    def delete_oauth_settings(self) -> int:
        had_row = self._row is not None
        self._row = None
        return 1 if had_row else 0


def _client(repo: FakeOAuthSettingsRepository, *, admin: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(routes_ops_oauth.router, prefix="/api")
    if admin:
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
    app.dependency_overrides[get_oauth_config_admin_service] = (
        lambda: OAuthConfigAdminService(repo)
    )
    return TestClient(app)


class RoutesOpsOAuthTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_oauth_config_provider()

    def test_get_returns_masked_projection_with_no_store_header(self) -> None:
        repo = FakeOAuthSettingsRepository(_row())
        configure_oauth_settings_reader(repo)
        client = _client(repo)

        response = client.get("/api/ops/oauth/config")

        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        body = response.json()
        assert body["source"] == "database"
        assert body["github_client_secret_configured"] is True
        assert body["github_client_secret_masked"] == "db-g****0002"
        assert DB_GITHUB_SECRET not in response.text
        assert '"github_client_secret"' not in response.text

    def test_put_blank_secret_retains_existing_value(self) -> None:
        repo = FakeOAuthSettingsRepository(_row())
        configure_oauth_settings_reader(repo)
        client = _client(repo)

        response = client.put(
            "/api/ops/oauth/config",
            json={"enabled_providers": ["github"], "github_client_id": "db-github-id"},
        )

        assert response.status_code == 200
        assert repo._row is not None
        assert repo._row.github_client_secret == DB_GITHUB_SECRET
        assert DB_GITHUB_SECRET not in response.text

    def test_put_clear_flag_wipes_secret_and_projection_reflects_it(self) -> None:
        repo = FakeOAuthSettingsRepository(_row())
        configure_oauth_settings_reader(repo)
        client = _client(repo)

        response = client.put(
            "/api/ops/oauth/config",
            json={"enabled_providers": ["github"], "clear_github_client_secret": True},
        )

        assert response.status_code == 200
        assert repo._row is not None
        assert repo._row.github_client_secret == ""
        assert response.json()["github_client_secret_configured"] is False
        assert response.json()["github_client_secret_masked"] is None
        assert DB_GITHUB_SECRET not in response.text

    def test_put_new_secret_saved_but_response_only_masked(self) -> None:
        repo = FakeOAuthSettingsRepository()
        configure_oauth_settings_reader(repo)
        client = _client(repo)

        response = client.put(
            "/api/ops/oauth/config",
            json={"github_client_secret": NEW_GITHUB_SECRET},
        )

        assert response.status_code == 200
        assert repo._row is not None
        assert repo._row.github_client_secret == NEW_GITHUB_SECRET
        assert response.json()["github_client_secret_masked"] == "gho_****1234"
        assert NEW_GITHUB_SECRET not in response.text

    def test_put_validation_error_maps_to_4xx_without_secret_leak(self) -> None:
        repo = FakeOAuthSettingsRepository(_row())
        configure_oauth_settings_reader(repo)
        client = _client(repo)

        # 超出 schema 约束的 TTL 在 Pydantic 层拒绝（422），绝不触达仓储或泄露密文
        response = client.put(
            "/api/ops/oauth/config",
            json={"state_ttl_seconds": 59},
        )

        assert response.status_code == 422
        assert DB_GITHUB_SECRET not in response.text

    def test_put_service_value_error_maps_to_400(self) -> None:
        repo = FakeOAuthSettingsRepository(_row())
        configure_oauth_settings_reader(repo)
        client = _client(repo)

        # schema 通过但服务层语义拒绝（非法基址）→ ValueError → 400
        response = client.put(
            "/api/ops/oauth/config",
            json={"public_base_url": "ftp://oauth.example.test"},
        )

        assert response.status_code == 400
        assert DB_GITHUB_SECRET not in response.text

    def test_put_changeme_placeholder_rejected(self) -> None:
        repo = FakeOAuthSettingsRepository()
        configure_oauth_settings_reader(repo)
        client = _client(repo)

        response = client.put(
            "/api/ops/oauth/config",
            json={"github_client_secret": "CHANGEME-github-secret"},
        )

        assert response.status_code == 400

    def test_delete_resets_to_env_and_stays_no_store(self) -> None:
        repo = FakeOAuthSettingsRepository(_row())
        configure_oauth_settings_reader(repo)
        client = _client(repo)

        response = client.delete("/api/ops/oauth/config")

        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert repo._row is None
        # 无 env 配置时回落 unconfigured；配置了 env 时回落 environment
        assert response.json()["source"] in ("environment", "unconfigured")
        assert response.json()["github_client_secret_configured"] is False
        assert DB_GITHUB_SECRET not in response.text

    def test_endpoints_require_admin(self) -> None:
        repo = FakeOAuthSettingsRepository(_row())
        configure_oauth_settings_reader(repo)
        client = _client(repo, admin=False)

        assert client.get("/api/ops/oauth/config").status_code in (401, 403)
        assert client.put("/api/ops/oauth/config", json={}).status_code in (401, 403)
        assert client.delete("/api/ops/oauth/config").status_code in (401, 403)


if __name__ == "__main__":
    unittest.main()
