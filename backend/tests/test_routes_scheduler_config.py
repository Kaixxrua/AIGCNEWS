from __future__ import annotations

from datetime import time
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import get_scheduler_config_admin_service
from backend.app.api.routes_ops import router as ops_router
from backend.app.core.auth import RequireAdmin
from backend.app.services.scheduler_config_admin import (
    SchedulerConfigAdminService,
    SchedulerJobConfigProjection,
)


def _config_client(service: SchedulerConfigAdminService) -> TestClient:
    app = FastAPI()
    app.include_router(ops_router, prefix="/api")
    app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
    app.dependency_overrides[get_scheduler_config_admin_service] = lambda: service
    return TestClient(app)


def test_list_scheduler_configs_returns_items_and_total() -> None:
    service = MagicMock(spec=SchedulerConfigAdminService)
    service.list_configs.return_value = [
        SchedulerJobConfigProjection(
            job_id="arxiv_papers",
            name="HuggingFace Papers 论文采集",
            start_time=time(0, 0),
            end_time=time(23, 59),
            interval_minutes=60,
            enabled=True,
        ),
    ]

    response = _config_client(service).get("/api/ops/scheduler/config")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["job_id"] == "arxiv_papers"
    assert body["items"][0]["start_time"] == "00:00:00"


def test_update_scheduler_config_persists_and_returns_item() -> None:
    service = MagicMock(spec=SchedulerConfigAdminService)
    service.update_config.return_value = SchedulerJobConfigProjection(
        job_id="arxiv_papers",
        name="HuggingFace Papers 论文采集",
        start_time=time(9, 0),
        end_time=time(17, 0),
        interval_minutes=90,
        enabled=True,
    )

    response = _config_client(service).put(
        "/api/ops/scheduler/config/arxiv_papers",
        json={
            "start_time": "09:00:00",
            "end_time": "17:00:00",
            "interval_minutes": 90,
            "enabled": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["item"]["interval_minutes"] == 90
    service.update_config.assert_called_once_with(
        "arxiv_papers",
        start_time=time(9, 0),
        end_time=time(17, 0),
        interval_minutes=90,
        enabled=True,
    )


def test_update_scheduler_config_applies_to_running_scheduler() -> None:
    projection = SchedulerJobConfigProjection(
        job_id="arxiv_papers",
        name="HuggingFace Papers 论文采集",
        start_time=time(9, 0),
        end_time=time(17, 0),
        interval_minutes=90,
        enabled=True,
    )
    service = MagicMock(spec=SchedulerConfigAdminService)
    service.update_config.return_value = projection
    runtime = MagicMock()
    runtime.apply_config_update.return_value = True

    client = _config_client(service)
    client.app.state.scheduler_runtime = runtime
    response = client.put(
        "/api/ops/scheduler/config/arxiv_papers",
        json={
            "start_time": "09:00:00",
            "end_time": "17:00:00",
            "interval_minutes": 90,
            "enabled": True,
        },
    )

    assert response.status_code == 200
    assert "即时生效" in response.json()["message"]
    runtime.apply_config_update.assert_called_once_with(projection)


def test_update_scheduler_config_falls_back_when_apply_fails() -> None:
    service = MagicMock(spec=SchedulerConfigAdminService)
    service.update_config.return_value = SchedulerJobConfigProjection(
        job_id="arxiv_papers",
        name="HuggingFace Papers 论文采集",
        start_time=time(9, 0),
        end_time=time(17, 0),
        interval_minutes=90,
        enabled=True,
    )
    runtime = MagicMock()
    runtime.apply_config_update.side_effect = RuntimeError("boom")

    client = _config_client(service)
    client.app.state.scheduler_runtime = runtime
    response = client.put(
        "/api/ops/scheduler/config/arxiv_papers",
        json={
            "start_time": "09:00:00",
            "end_time": "17:00:00",
            "interval_minutes": 90,
            "enabled": True,
        },
    )

    assert response.status_code == 200
    assert "重启后生效" in response.json()["message"]


def test_update_scheduler_config_returns_400_on_service_error() -> None:
    service = MagicMock(spec=SchedulerConfigAdminService)
    service.update_config.side_effect = ValueError("未知定时任务: missing")

    response = _config_client(service).put(
        "/api/ops/scheduler/config/missing",
        json={
            "start_time": "09:00:00",
            "end_time": "17:00:00",
            "interval_minutes": 90,
            "enabled": True,
        },
    )

    assert response.status_code == 400
    assert "missing" in response.json()["detail"]


def test_scheduler_config_routes_require_admin() -> None:
    app = FastAPI()
    app.include_router(ops_router, prefix="/api")
    service = MagicMock(spec=SchedulerConfigAdminService)
    app.dependency_overrides[get_scheduler_config_admin_service] = lambda: service

    client = TestClient(app)
    list_response = client.get("/api/ops/scheduler/config")
    update_response = client.put(
        "/api/ops/scheduler/config/arxiv_papers",
        json={"start_time": "09:00:00", "end_time": "17:00:00", "interval_minutes": 90, "enabled": True},
    )

    assert list_response.status_code in (401, 403)
    assert update_response.status_code in (401, 403)
    service.list_configs.assert_not_called()
    service.update_config.assert_not_called()
