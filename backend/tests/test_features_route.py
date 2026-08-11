"""特性开关端点契约：公开只读、实时反映 settings 单例。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes_features import router
from backend.app.core.config import settings


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


class TestFeaturesRoute:
    def test_flags_off(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "x_source_enabled", False)
        monkeypatch.setattr(settings, "wechat_source_enabled", False)

        response = client.get("/api/features")

        assert response.status_code == 200
        assert response.json() == {"x_source": False, "wechat_source": False}

    def test_flags_on(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "x_source_enabled", True)
        monkeypatch.setattr(settings, "wechat_source_enabled", True)

        response = client.get("/api/features")

        assert response.status_code == 200
        assert response.json() == {"x_source": True, "wechat_source": True}

    def test_requires_no_auth(self, client: TestClient) -> None:
        # 未携带任何凭据即可读取（前端首屏导航依赖该端点）
        assert client.get("/api/features").status_code == 200
