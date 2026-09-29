"""特性开关端点契约：公开只读、实时反映 settings 单例。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes_features import router
from backend.app.core.config import settings
from backend.app.services.push.telegram_config_provider import (
    reset_telegram_config_provider,
)


@pytest.fixture()
def client() -> TestClient:
    # 防并行测试污染：telegram 配置 reader 若被其他用例绑定会走 DB 路径。
    reset_telegram_config_provider()
    app = FastAPI()
    app.state.redis = None
    app.include_router(router, prefix="/api")
    return TestClient(app)


class TestFeaturesRoute:
    def test_flags_off(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "x_source_enabled", False)
        monkeypatch.setattr(settings, "telegram_push_enabled", False)

        response = client.get("/api/features")

        assert response.status_code == 200
        assert response.json() == {
            "x_source": False,
            "oauth_providers": [],
            "telegram_push_enabled": False,
        }

    def test_flags_on(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "x_source_enabled", True)
        monkeypatch.setattr(settings, "telegram_push_enabled", True)

        response = client.get("/api/features")

        assert response.status_code == 200
        assert response.json() == {
            "x_source": True,
            "oauth_providers": [],
            "telegram_push_enabled": True,
        }

    def test_configured_provider_requires_redis(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "oauth_enabled_providers", "wechat,github")
        monkeypatch.setattr(settings, "public_base_url", "https://aigcnews.example")
        monkeypatch.setattr(settings, "github_oauth_client_id", "github-client")
        monkeypatch.setattr(settings, "github_oauth_client_secret", "github-secret")
        monkeypatch.setattr(settings, "wechat_oauth_app_id", "")
        monkeypatch.setattr(settings, "wechat_oauth_app_secret", "")

        assert client.get("/api/features").json()["oauth_providers"] == []

        client.app.state.redis = object()
        assert client.get("/api/features").json()["oauth_providers"] == ["github"]

    def test_wechat_source_flag_is_gone(self, client: TestClient) -> None:
        # 微信公众号功能已整体移除：端点不再暴露 wechat_source 键
        assert "wechat_source" not in client.get("/api/features").json()

    def test_requires_no_auth(self, client: TestClient) -> None:
        # 未携带任何凭据即可读取（前端首屏导航依赖该端点）
        assert client.get("/api/features").status_code == 200
