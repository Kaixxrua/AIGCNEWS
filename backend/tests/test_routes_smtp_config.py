from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import get_smtp_config_admin_service
from backend.app.api.routes_ops import router as ops_router
from backend.app.core.auth import RequireAdmin
from backend.app.services.smtp_config_admin import (
    SmtpConfigAdminService,
    SmtpConfigProjection,
    SmtpNotConfiguredError,
    SmtpTestDeliveryError,
)


def _projection(**overrides) -> SmtpConfigProjection:
    values = {
        "host": "smtp.example.test",
        "port": 465,
        "username": "smtp-user",
        "password_configured": True,
        "password_masked": "smt****word",
        "from_email": "sender@example.test",
        "from_name": "AIGC",
        "use_tls": True,
        "source": "database",
        "updated_at": "2026-08-12T10:00:00+00:00",
    }
    values.update(overrides)
    return SmtpConfigProjection(**values)


def _smtp_client(
    service: SmtpConfigAdminService, identity: dict | None = None
) -> TestClient:
    app = FastAPI()
    app.include_router(ops_router, prefix="/api")
    app.dependency_overrides[RequireAdmin] = lambda: (
        identity if identity is not None else {"role": "admin", "email": "admin@example.test"}
    )
    app.dependency_overrides[get_smtp_config_admin_service] = lambda: service
    return TestClient(app)


def test_get_smtp_config_returns_projection_without_plaintext_password() -> None:
    service = MagicMock(spec=SmtpConfigAdminService)
    service.get_config.return_value = _projection()

    response = _smtp_client(service).get("/api/ops/smtp/config")

    assert response.status_code == 200
    body = response.json()
    assert body["host"] == "smtp.example.test"
    assert body["source"] == "database"
    assert body["password_configured"] is True
    assert body["password_masked"] == "smt****word"
    # 响应契约绝不明文回传密码
    assert "password" not in body
    assert "smt0-secr3t" not in str(body)


def test_update_smtp_config_returns_saved_projection() -> None:
    service = MagicMock(spec=SmtpConfigAdminService)
    service.update_config.return_value = _projection(host="smtp.saved.test")

    response = _smtp_client(service).put(
        "/api/ops/smtp/config",
        json={
            "host": "smtp.saved.test",
            "port": 587,
            "username": "user",
            "password": None,
            "clear_password": False,
            "from_email": "sender@example.test",
            "from_name": "AIGC",
            "use_tls": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["host"] == "smtp.saved.test"
    service.update_config.assert_called_once()
    payload = service.update_config.call_args.args[0]
    assert payload["host"] == "smtp.saved.test"
    assert payload["password"] is None


def test_update_smtp_config_maps_validation_error_to_400() -> None:
    service = MagicMock(spec=SmtpConfigAdminService)
    service.update_config.side_effect = ValueError("发件邮箱格式不正确")

    response = _smtp_client(service).put(
        "/api/ops/smtp/config",
        json={
            "host": "smtp.saved.test",
            "port": 587,
            "username": "",
            "password": None,
            "clear_password": False,
            "from_email": "not-an-email",
            "from_name": "",
            "use_tls": True,
        },
    )

    assert response.status_code == 400
    assert "发件邮箱" in response.json()["detail"]


def test_test_smtp_with_explicit_recipient() -> None:
    service = MagicMock(spec=SmtpConfigAdminService)
    service.send_test_email.return_value = {
        "status": "success",
        "message": "测试邮件已发送至 ops@example-mail.com",
        "to_email": "ops@example-mail.com",
        "latency_ms": 320,
    }

    response = _smtp_client(service).post(
        "/api/ops/smtp/test", json={"to_email": "ops@example-mail.com"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["latency_ms"] == 320
    service.send_test_email.assert_called_once_with("ops@example-mail.com")


def test_test_smtp_defaults_to_admin_identity_email() -> None:
    service = MagicMock(spec=SmtpConfigAdminService)
    service.send_test_email.return_value = {
        "status": "success",
        "message": "测试邮件已发送至 admin@example.test",
        "to_email": "admin@example.test",
        "latency_ms": 250,
    }

    response = _smtp_client(service).post("/api/ops/smtp/test", json={})

    assert response.status_code == 200
    service.send_test_email.assert_called_once_with("admin@example.test")


def test_test_smtp_returns_400_when_recipient_unresolvable() -> None:
    service = MagicMock(spec=SmtpConfigAdminService)

    response = _smtp_client(service, identity={"role": "admin"}).post(
        "/api/ops/smtp/test", json={}
    )

    assert response.status_code == 400
    assert "to_email" in response.json()["detail"]
    service.send_test_email.assert_not_called()


def test_test_smtp_maps_unconfigured_to_400() -> None:
    service = MagicMock(spec=SmtpConfigAdminService)
    service.send_test_email.side_effect = SmtpNotConfiguredError(
        "SMTP 未配置：请先保存配置或设置 SMTP_HOST 环境变量"
    )

    response = _smtp_client(service).post(
        "/api/ops/smtp/test", json={"to_email": "ops@example-mail.com"}
    )

    assert response.status_code == 400
    assert "SMTP 未配置" in response.json()["detail"]


def test_test_smtp_maps_delivery_failure_to_502() -> None:
    service = MagicMock(spec=SmtpConfigAdminService)
    service.send_test_email.side_effect = SmtpTestDeliveryError(
        "邮件发送失败（SMTPAuthenticationError），请检查 SMTP 配置后重试"
    )

    response = _smtp_client(service).post(
        "/api/ops/smtp/test", json={"to_email": "ops@example-mail.com"}
    )

    assert response.status_code == 502
    assert "SMTPAuthenticationError" in response.json()["detail"]


def test_smtp_routes_require_admin() -> None:
    app = FastAPI()
    app.include_router(ops_router, prefix="/api")
    service = MagicMock(spec=SmtpConfigAdminService)
    app.dependency_overrides[get_smtp_config_admin_service] = lambda: service

    client = TestClient(app)
    get_response = client.get("/api/ops/smtp/config")
    put_response = client.put(
        "/api/ops/smtp/config",
        json={
            "host": "smtp.saved.test",
            "port": 587,
            "username": "",
            "password": None,
            "clear_password": False,
            "from_email": "sender@example.test",
            "from_name": "",
            "use_tls": True,
        },
    )
    test_response = client.post("/api/ops/smtp/test", json={})

    assert get_response.status_code in (401, 403)
    assert put_response.status_code in (401, 403)
    assert test_response.status_code in (401, 403)
    service.get_config.assert_not_called()
    service.update_config.assert_not_called()
    service.send_test_email.assert_not_called()
