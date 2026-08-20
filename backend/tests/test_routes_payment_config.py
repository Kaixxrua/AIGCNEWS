"""GET/PUT/DELETE /ops/payments/config 路由契约测试。

钉住的对外语义：
- 三动词一律 RequireAdmin（未登录/非管理员 → 401/403，服务不被触碰）；
- GET/PUT/DELETE 响应只含脱敏投影，绝不回明文密钥；
- 服务层 ValueError 映射 400。
"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import get_payment_config_admin_service
from backend.app.api.routes_ops import router as ops_router
from backend.app.core.auth import RequireAdmin
from backend.app.services.payments.config_admin import (
    PaymentConfigAdminService,
    PaymentConfigProjection,
)


def _projection(**overrides) -> PaymentConfigProjection:
    values = {
        "enabled": True,
        "order_ttl_minutes": 30,
        "public_base_url": "https://pay.example.test",
        "wechat_appid": "wx123",
        "wechat_mchid": "1600000000",
        "wechat_mch_serial_no": "SERIAL",
        "alipay_appid": "",
        "source": "database",
        "updated_at": "2026-08-20T10:00:00+00:00",
        "wechat_configured": True,
        "alipay_configured": False,
        "stripe_configured": True,
        "wechat_api_v3_key_configured": True,
        "wechat_api_v3_key_masked": "abcd****wxyz",
        "wechat_private_key_pem_configured": True,
        "wechat_private_key_pem_masked": "----****----",
        "alipay_private_key_pem_configured": False,
        "alipay_private_key_pem_masked": None,
        "alipay_public_key_pem_configured": False,
        "alipay_public_key_pem_masked": None,
        "stripe_secret_key_configured": True,
        "stripe_secret_key_masked": "sk_l****cret",
        "stripe_webhook_secret_configured": True,
        "stripe_webhook_secret_masked": "whse****cret",
    }
    values.update(overrides)
    return PaymentConfigProjection(**values)


def _client(service: PaymentConfigAdminService, identity: dict | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(ops_router, prefix="/api")
    app.dependency_overrides[RequireAdmin] = lambda: (
        identity if identity is not None else {"role": "admin", "email": "admin@example.test"}
    )
    app.dependency_overrides[get_payment_config_admin_service] = lambda: service
    return TestClient(app)


def test_get_payment_config_returns_masked_projection_without_plaintext() -> None:
    service = MagicMock(spec=PaymentConfigAdminService)
    service.get_config.return_value = _projection()

    response = _client(service).get("/api/ops/payments/config")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["source"] == "database"
    assert body["stripe_secret_key_configured"] is True
    assert body["stripe_secret_key_masked"] == "sk_l****cret"
    # 响应契约绝不明文回传密钥：不存在未脱敏的密文字段键
    assert "stripe_secret_key" not in body
    assert "wechat_api_v3_key" not in body
    assert "wechat_private_key_pem" not in body
    assert "alipay_private_key_pem" not in body


def test_update_payment_config_passes_payload_and_returns_projection() -> None:
    service = MagicMock(spec=PaymentConfigAdminService)
    service.update_config.return_value = _projection(public_base_url="https://saved.example.test")

    response = _client(service).put(
        "/api/ops/payments/config",
        json={
            "enabled": True,
            "order_ttl_minutes": 60,
            "public_base_url": "https://saved.example.test",
            "wechat_appid": "wx123",
            "stripe_secret_key": None,
            "clear_stripe_webhook_secret": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["public_base_url"] == "https://saved.example.test"
    service.update_config.assert_called_once()
    payload = service.update_config.call_args.args[0]
    assert payload["order_ttl_minutes"] == 60
    assert payload["stripe_secret_key"] is None
    assert payload["clear_stripe_webhook_secret"] is True


def test_update_payment_config_maps_validation_error_to_400() -> None:
    service = MagicMock(spec=PaymentConfigAdminService)
    service.update_config.side_effect = ValueError("订单过期分钟数必须在 5-1440 之间")

    response = _client(service).put(
        "/api/ops/payments/config",
        json={"enabled": True, "order_ttl_minutes": 30},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "订单过期分钟数必须在 5-1440 之间"


def test_delete_payment_config_resets_to_environment() -> None:
    service = MagicMock(spec=PaymentConfigAdminService)
    service.reset_config.return_value = _projection(source="environment", updated_at=None)

    response = _client(service).delete("/api/ops/payments/config")

    assert response.status_code == 200
    assert response.json()["source"] == "environment"
    service.reset_config.assert_called_once()


def test_payment_config_routes_require_admin() -> None:
    app = FastAPI()
    app.include_router(ops_router, prefix="/api")
    service = MagicMock(spec=PaymentConfigAdminService)
    app.dependency_overrides[get_payment_config_admin_service] = lambda: service

    client = TestClient(app)
    get_response = client.get("/api/ops/payments/config")
    put_response = client.put(
        "/api/ops/payments/config",
        json={"enabled": True, "order_ttl_minutes": 30},
    )
    delete_response = client.delete("/api/ops/payments/config")

    assert get_response.status_code in (401, 403)
    assert put_response.status_code in (401, 403)
    assert delete_response.status_code in (401, 403)
    service.get_config.assert_not_called()
    service.update_config.assert_not_called()
    service.reset_config.assert_not_called()
