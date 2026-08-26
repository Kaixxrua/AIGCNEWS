"""GET/PUT/DELETE /api/ops/telegram/config 与 webhook 注册的路由契约测试。

钉住的对外语义：
- 全部端点 RequireAdmin，且响应 Cache-Control: no-store；
- 任何响应都不回明文密钥（投影只有 *_configured + *_masked）；
- PUT 的 schema 越界 → 422、服务层 ValueError → 400，且不泄露已有密文。
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_ops_telegram
from backend.app.api.dependencies import get_telegram_config_admin_service
from backend.app.core.auth import RequireAdmin
from backend.app.repositories.telegram_settings_repository import TelegramSettings
from backend.app.services.push.telegram_config_admin import TelegramConfigAdminService
from backend.app.services.push.telegram_config_provider import (
    configure_telegram_settings_reader,
    reset_telegram_config_provider,
)

DB_BOT_TOKEN = "db-bot-token-0002"
NEW_BOT_TOKEN = "110000:new-bot-token-0003"


def _row(**overrides) -> TelegramSettings:
    values = {
        "enabled": True,
        "bot_token": DB_BOT_TOKEN,
        "bot_username": "db_bot",
        "webhook_secret": "db-webhook-secret-0004",
        "link_ttl_seconds": 300,
        "request_timeout_seconds": 5.0,
        "updated_at": datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return TelegramSettings(**values)


class FakeTelegramSettingsRepository:
    def __init__(self, row: TelegramSettings | None = None) -> None:
        self._row = row

    def get_telegram_settings(self) -> TelegramSettings | None:
        return self._row

    def upsert_telegram_settings(self, **kwargs) -> TelegramSettings:
        self._row = TelegramSettings(
            **kwargs,
            updated_at=datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc),
        )
        return self._row

    def delete_telegram_settings(self) -> int:
        had_row = self._row is not None
        self._row = None
        return 1 if had_row else 0


def _telegram_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/getMe"):
            return httpx.Response(
                200, json={"ok": True, "result": {"id": 1, "username": "ops_bot"}}
            )
        if path.endswith("/getWebhookInfo"):
            return httpx.Response(
                200,
                json={"ok": True, "result": {"url": "", "pending_update_count": 0}},
            )
        if path.endswith("/setWebhook"):
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(404, json={"ok": False})

    return httpx.MockTransport(handler)


def _client(repo: FakeTelegramSettingsRepository, *, admin: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(routes_ops_telegram.router, prefix="/api")
    if admin:
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
    app.dependency_overrides[get_telegram_config_admin_service] = (
        lambda: TelegramConfigAdminService(repo, transport=_telegram_transport())
    )
    return TestClient(app)


class RoutesOpsTelegramTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_telegram_config_provider()

    def test_get_returns_masked_projection_with_no_store_header(self) -> None:
        repo = FakeTelegramSettingsRepository(_row())
        configure_telegram_settings_reader(repo)
        client = _client(repo)

        response = client.get("/api/ops/telegram/config")

        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        body = response.json()
        assert body["source"] == "database"
        assert body["enabled"] is True
        assert body["bot_token_configured"] is True
        assert body["bot_token_masked"] == "db-b****0002"
        assert DB_BOT_TOKEN not in response.text
        assert '"bot_token"' not in response.text

    def test_put_blank_secret_retains_existing_value(self) -> None:
        repo = FakeTelegramSettingsRepository(_row())
        configure_telegram_settings_reader(repo)
        client = _client(repo)

        response = client.put(
            "/api/ops/telegram/config",
            json={"enabled": True, "bot_username": "db_bot"},
        )

        assert response.status_code == 200
        assert repo._row is not None
        assert repo._row.bot_token == DB_BOT_TOKEN
        assert DB_BOT_TOKEN not in response.text

    def test_put_new_token_saved_but_response_only_masked(self) -> None:
        repo = FakeTelegramSettingsRepository()
        configure_telegram_settings_reader(repo)
        client = _client(repo)

        response = client.put(
            "/api/ops/telegram/config",
            json={"enabled": True, "bot_token": NEW_BOT_TOKEN},
        )

        assert response.status_code == 200
        assert repo._row is not None
        assert repo._row.bot_token == NEW_BOT_TOKEN
        # getMe 校验成功 → username 以 Telegram 返回为准
        assert repo._row.bot_username == "ops_bot"
        assert response.json()["bot_token_masked"] == "1100****0003"
        assert NEW_BOT_TOKEN not in response.text

    def test_put_schema_violation_maps_to_422(self) -> None:
        repo = FakeTelegramSettingsRepository(_row())
        configure_telegram_settings_reader(repo)
        client = _client(repo)

        response = client.put(
            "/api/ops/telegram/config",
            json={"link_ttl_seconds": 59},
        )

        assert response.status_code == 422
        assert DB_BOT_TOKEN not in response.text

    def test_put_service_value_error_maps_to_400(self) -> None:
        repo = FakeTelegramSettingsRepository(_row())
        configure_telegram_settings_reader(repo)
        client = _client(repo)

        response = client.put(
            "/api/ops/telegram/config",
            json={"bot_token": "CHANGEME-token"},
        )

        assert response.status_code == 400
        assert DB_BOT_TOKEN not in response.text

    def test_delete_resets_to_env_and_stays_no_store(self) -> None:
        repo = FakeTelegramSettingsRepository(_row())
        configure_telegram_settings_reader(repo)
        client = _client(repo)

        response = client.delete("/api/ops/telegram/config")

        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert repo._row is None
        assert response.json()["source"] in ("environment", "unconfigured")
        assert response.json()["bot_token_configured"] is False
        assert DB_BOT_TOKEN not in response.text

    def test_register_webhook_endpoint(self) -> None:
        repo = FakeTelegramSettingsRepository(_row())
        configure_telegram_settings_reader(repo)
        client = _client(repo)

        response = client.post("/api/ops/telegram/config/webhook")

        # 默认 env 无 public_base_url → 服务层 ValueError → 400
        assert response.status_code == 400
        assert DB_BOT_TOKEN not in response.text

    def test_endpoints_require_admin(self) -> None:
        repo = FakeTelegramSettingsRepository(_row())
        configure_telegram_settings_reader(repo)
        client = _client(repo, admin=False)

        assert client.get("/api/ops/telegram/config").status_code in (401, 403)
        assert client.put("/api/ops/telegram/config", json={}).status_code in (401, 403)
        assert client.delete("/api/ops/telegram/config").status_code in (401, 403)
        assert client.post("/api/ops/telegram/config/webhook").status_code in (401, 403)


if __name__ == "__main__":
    unittest.main()
