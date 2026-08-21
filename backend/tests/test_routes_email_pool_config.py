from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import (
    get_email_pool_config_admin_service,
    get_push_delivery_repository,
)
from backend.app.api.routes_ops import router as ops_router
from backend.app.core.auth import RequireAdmin
from backend.app.services.email_pool_config_admin import (
    EmailPoolConfigAdminService,
    EmailPoolConfigProjection,
    EmailPoolEntryProjection,
    EmailPoolNotConfiguredError,
    EmailPoolTestDeliveryError,
)


def _entry_projection(**overrides) -> EmailPoolEntryProjection:
    values = {
        "name": "brevo",
        "host": "smtp-relay.brevo.test",
        "port": 587,
        "username": "pool-user",
        "password_configured": True,
        "password_masked": "db-s****-key",
        "from_email": "noreply@example.test",
        "from_name": "AIGC",
        "use_tls": True,
        "daily_limit": 280,
        "monthly_limit": 8500,
        "priority": 20,
    }
    values.update(overrides)
    return EmailPoolEntryProjection(**values)


def _projection(**overrides) -> EmailPoolConfigProjection:
    values = {
        "entries": [_entry_projection()],
        "source": "database",
        "updated_at": "2026-08-14T10:00:00+00:00",
    }
    values.update(overrides)
    return EmailPoolConfigProjection(**values)


def _pool_client(
    service: EmailPoolConfigAdminService, identity: dict | None = None
) -> TestClient:
    app = FastAPI()
    app.include_router(ops_router, prefix="/api")
    app.dependency_overrides[RequireAdmin] = lambda: (
        identity if identity is not None else {"role": "admin", "email": "admin@example.test"}
    )
    app.dependency_overrides[get_email_pool_config_admin_service] = lambda: service
    return TestClient(app)


def _entry_payload(**overrides) -> dict:
    payload = {
        "name": "brevo",
        "host": "smtp-relay.brevo.test",
        "port": 587,
        "username": "user",
        "password": None,
        "clear_password": False,
        "from_email": "",
        "from_name": "",
        "use_tls": True,
        "daily_limit": 280,
        "monthly_limit": 8500,
        "priority": 20,
    }
    payload.update(overrides)
    return payload


def test_get_email_pool_config_returns_projection_without_plaintext_password() -> None:
    service = MagicMock(spec=EmailPoolConfigAdminService)
    service.get_config.return_value = _projection()

    response = _pool_client(service).get("/api/ops/email-pool/config")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "database"
    entry = body["entries"][0]
    assert entry["name"] == "brevo"
    assert entry["password_configured"] is True
    assert entry["password_masked"] == "db-s****-key"
    # 响应契约绝不明文回传密码
    assert "password" not in entry
    assert "db-secret-key" not in str(body)


def test_update_email_pool_config_returns_saved_projection() -> None:
    service = MagicMock(spec=EmailPoolConfigAdminService)
    service.update_config.return_value = _projection()

    response = _pool_client(service).put(
        "/api/ops/email-pool/config",
        json={"entries": [_entry_payload()]},
    )

    assert response.status_code == 200
    assert response.json()["entries"][0]["name"] == "brevo"
    service.update_config.assert_called_once()
    payload = service.update_config.call_args.args[0]
    assert payload["entries"][0]["name"] == "brevo"
    assert payload["entries"][0]["password"] is None


def test_update_email_pool_config_empty_entries_is_allowed() -> None:
    # 空数组 = 删除 DB 覆盖行回退 env，属合法请求而非 422
    service = MagicMock(spec=EmailPoolConfigAdminService)
    service.update_config.return_value = _projection(entries=[], source="unconfigured")

    response = _pool_client(service).put(
        "/api/ops/email-pool/config", json={"entries": []}
    )

    assert response.status_code == 200
    assert response.json()["entries"] == []
    assert response.json()["source"] == "unconfigured"


def test_update_email_pool_config_maps_validation_error_to_400() -> None:
    service = MagicMock(spec=EmailPoolConfigAdminService)
    service.update_config.side_effect = ValueError("服务商名称重复：brevo")

    response = _pool_client(service).put(
        "/api/ops/email-pool/config",
        json={"entries": [_entry_payload(), _entry_payload()]},
    )

    assert response.status_code == 400
    assert "重复" in response.json()["detail"]


def test_update_email_pool_config_rejects_schema_violation_with_422() -> None:
    service = MagicMock(spec=EmailPoolConfigAdminService)

    response = _pool_client(service).put(
        "/api/ops/email-pool/config",
        json={"entries": [_entry_payload(port=70000)]},
    )

    assert response.status_code == 422
    service.update_config.assert_not_called()


def test_test_email_pool_with_explicit_recipient() -> None:
    service = MagicMock(spec=EmailPoolConfigAdminService)
    service.send_test_email.return_value = {
        "status": "success",
        "message": "测试邮件已经过 brevo 投递至 ops@example-mail.com",
        "to_email": "ops@example-mail.com",
        "provider": "brevo",
        "latency_ms": 480,
    }

    response = _pool_client(service).post(
        "/api/ops/email-pool/test", json={"to_email": "ops@example-mail.com"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["provider"] == "brevo"
    assert body["latency_ms"] == 480
    service.send_test_email.assert_called_once_with("ops@example-mail.com")


def test_test_email_pool_defaults_to_admin_identity_email() -> None:
    service = MagicMock(spec=EmailPoolConfigAdminService)
    service.send_test_email.return_value = {
        "status": "success",
        "message": "测试邮件已经过 brevo 投递至 admin@example.test",
        "to_email": "admin@example.test",
        "provider": "brevo",
        "latency_ms": 250,
    }

    response = _pool_client(service).post("/api/ops/email-pool/test", json={})

    assert response.status_code == 200
    service.send_test_email.assert_called_once_with("admin@example.test")


def test_test_email_pool_returns_400_when_recipient_unresolvable() -> None:
    service = MagicMock(spec=EmailPoolConfigAdminService)

    response = _pool_client(service, identity={"role": "admin"}).post(
        "/api/ops/email-pool/test", json={}
    )

    assert response.status_code == 400
    assert "to_email" in response.json()["detail"]
    service.send_test_email.assert_not_called()


def test_test_email_pool_maps_unconfigured_to_400() -> None:
    service = MagicMock(spec=EmailPoolConfigAdminService)
    service.send_test_email.side_effect = EmailPoolNotConfiguredError(
        "邮件池未配置：请先保存池配置或设置 EMAIL_POOL_JSON 环境变量"
    )

    response = _pool_client(service).post(
        "/api/ops/email-pool/test", json={"to_email": "ops@example-mail.com"}
    )

    assert response.status_code == 400
    assert "邮件池未配置" in response.json()["detail"]


def test_test_email_pool_maps_delivery_failure_to_502() -> None:
    service = MagicMock(spec=EmailPoolConfigAdminService)
    service.send_test_email.side_effect = EmailPoolTestDeliveryError(
        "邮件池内全部服务商投递失败或不可用，请检查各服务商配置与配额"
    )

    response = _pool_client(service).post(
        "/api/ops/email-pool/test", json={"to_email": "ops@example-mail.com"}
    )

    assert response.status_code == 502
    assert "全部服务商" in response.json()["detail"]


def test_email_pool_routes_require_admin() -> None:
    app = FastAPI()
    app.include_router(ops_router, prefix="/api")
    service = MagicMock(spec=EmailPoolConfigAdminService)
    app.dependency_overrides[get_email_pool_config_admin_service] = lambda: service

    client = TestClient(app)
    get_response = client.get("/api/ops/email-pool/config")
    put_response = client.put(
        "/api/ops/email-pool/config",
        json={"entries": [_entry_payload()]},
    )
    test_response = client.post("/api/ops/email-pool/test", json={})
    stats_response = client.get("/api/ops/email-pool/delivery-stats")

    assert get_response.status_code in (401, 403)
    assert put_response.status_code in (401, 403)
    assert test_response.status_code in (401, 403)
    assert stats_response.status_code in (401, 403)
    service.get_config.assert_not_called()
    service.update_config.assert_not_called()
    service.send_test_email.assert_not_called()


# ── 邮件投递统计 ─────────────────────────────────────────────────────────────


def _stats_client(repository: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(ops_router, prefix="/api")
    app.dependency_overrides[RequireAdmin] = lambda: {
        "role": "admin",
        "email": "admin@example.test",
    }
    app.dependency_overrides[get_push_delivery_repository] = lambda: repository
    return TestClient(app)


def test_get_email_delivery_stats_returns_day_buckets() -> None:
    repository = MagicMock()
    repository.count_email_deliveries_by_day.return_value = [
        {"date": "2026-08-21", "sent": 12, "failed": 1},
        {"date": "2026-08-20", "sent": 9, "failed": 0},
    ]

    response = _stats_client(repository).get("/api/ops/email-pool/delivery-stats")

    assert response.status_code == 200
    assert response.json() == {
        "days": [
            {"date": "2026-08-21", "sent": 12, "failed": 1},
            {"date": "2026-08-20", "sent": 9, "failed": 0},
        ]
    }
    # 端点固定查询最近 7 天窗口
    repository.count_email_deliveries_by_day.assert_called_once_with(days=7)


def test_get_email_delivery_stats_returns_empty_list_when_no_deliveries() -> None:
    repository = MagicMock()
    repository.count_email_deliveries_by_day.return_value = []

    response = _stats_client(repository).get("/api/ops/email-pool/delivery-stats")

    assert response.status_code == 200
    assert response.json() == {"days": []}
