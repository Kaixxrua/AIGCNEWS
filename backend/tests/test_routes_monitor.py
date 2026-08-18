from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_monitor
from backend.app.api.dependencies import (
    get_briefing_repository,
    get_document_repository,
    get_error_event_repository,
    get_evaluation_repository,
    get_health_check_service,
    get_ingestion_task_repository,
    get_readiness_check,
)
from backend.app.core.auth import RequireAdmin, RequireUser
from backend.app.repositories.briefing_repository import BriefingReader
from backend.app.repositories.document_repository import DocumentStatisticsReader
from backend.app.repositories.error_event_repository import ErrorEventReader
from backend.app.repositories.evaluation_repository import EvaluationSummaryReader
from backend.app.repositories.task_repository import (
    MonitorTaskRepository,
    RecentTaskReader,
)


class MonitorRouteTests(unittest.TestCase):
    def test_readiness_uses_injected_check(self) -> None:
        app = FastAPI()
        app.include_router(routes_monitor.router, prefix="/api")
        check = MagicMock(
            return_value={
                "backend": "postgres",
                "runtime_ready": True,
            }
        )
        app.dependency_overrides[get_readiness_check] = lambda: check

        response = TestClient(app).get("/api/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), check.return_value)
        check.assert_called_once_with()

    def test_readiness_preserves_unavailable_projection(self) -> None:
        app = FastAPI()
        app.include_router(routes_monitor.router, prefix="/api")
        check = MagicMock(
            return_value={
                "backend": "postgres",
                "runtime_ready": False,
            }
        )
        app.dependency_overrides[get_readiness_check] = lambda: check

        response = TestClient(app).get("/api/ready")

        self.assertEqual(response.status_code, 503)
        # 匿名就绪探针只回中性状态，不回显内部细节
        self.assertEqual(
            response.json(),
            {"detail": {"status": "not_ready", "runtime_ready": False}},
        )
        check.assert_called_once_with()

    def test_readiness_never_leaks_internal_error_class(self) -> None:
        app = FastAPI()
        app.include_router(routes_monitor.router, prefix="/api")
        check = MagicMock(
            return_value={
                "backend": "postgres",
                "runtime_ready": False,
                "error_class": "OperationalError",
                "dependency": "postgres",
            }
        )
        app.dependency_overrides[get_readiness_check] = lambda: check

        response = TestClient(app).get("/api/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": {"status": "not_ready", "runtime_ready": False}},
        )
        self.assertNotIn("OperationalError", response.text)
        self.assertNotIn("error_class", response.text)

    def test_health_check_uses_injected_service(self) -> None:
        app = FastAPI()
        app.include_router(routes_monitor.router, prefix="/api")
        service = MagicMock()
        service.run.return_value = {
            "status": "degraded",
            "elapsed_seconds": 0.123,
            "services": {"postgres": {"status": "error"}},
        }
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[get_health_check_service] = lambda: service

        response = TestClient(app).get("/api/monitor/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), service.run.return_value)
        service.run.assert_called_once_with()

    def test_health_check_requires_admin_before_service_calls(self) -> None:
        app = FastAPI()
        app.include_router(routes_monitor.router, prefix="/api")
        service = MagicMock()
        app.dependency_overrides[get_health_check_service] = lambda: service

        response = TestClient(app).get("/api/monitor/health")

        self.assertIn(response.status_code, (401, 403))
        service.run.assert_not_called()

    def test_health_check_rejects_authenticated_non_admin(self) -> None:
        app = FastAPI()
        app.include_router(routes_monitor.router, prefix="/api")
        service = MagicMock()
        # 已登录但非管理员：真实 RequireAdmin 在被覆盖的 RequireUser 之上判 403
        app.dependency_overrides[RequireUser] = lambda: {"role": "user"}
        app.dependency_overrides[get_health_check_service] = lambda: service

        response = TestClient(app).get("/api/monitor/health")

        self.assertEqual(response.status_code, 403)
        service.run.assert_not_called()

    def test_system_metrics_passes_evaluation_repository_to_collector(self) -> None:
        app = FastAPI()
        app.include_router(routes_monitor.router, prefix="/api")
        collector = MagicMock(return_value={"uptime_seconds": 1.0})
        evaluation_reader = MagicMock(spec=EvaluationSummaryReader)
        task_reader = MagicMock(spec=RecentTaskReader)
        document_statistics = MagicMock(spec=DocumentStatisticsReader)
        briefing_reader = MagicMock(spec=BriefingReader)

        def override_require_admin() -> dict[str, str]:
            return {"role": "admin"}

        app.dependency_overrides[RequireAdmin] = override_require_admin
        app.dependency_overrides[
            get_evaluation_repository
        ] = lambda: evaluation_reader
        app.dependency_overrides[get_ingestion_task_repository] = lambda: task_reader
        app.dependency_overrides[get_document_repository] = lambda: document_statistics
        app.dependency_overrides[get_briefing_repository] = lambda: briefing_reader

        with unittest.mock.patch(
            "backend.app.monitoring.metrics.collect_metrics",
            collector,
        ):
            response = TestClient(app).get("/api/monitor/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"uptime_seconds": 1.0})
        collector.assert_called_once_with(
            task_reader=task_reader,
            evaluation_reader=evaluation_reader,
            document_statistics=document_statistics,
            briefing_reader=briefing_reader,
            mcp_tool_calls_snapshot=unittest.mock.ANY,
        )

    def test_system_metrics_rejects_authenticated_non_admin(self) -> None:
        app = FastAPI()
        app.include_router(routes_monitor.router, prefix="/api")
        collector = MagicMock(return_value={"uptime_seconds": 1.0})
        app.dependency_overrides[RequireUser] = lambda: {"role": "user"}

        with unittest.mock.patch(
            "backend.app.monitoring.metrics.collect_metrics",
            collector,
        ):
            response = TestClient(app).get("/api/monitor/metrics")

        self.assertEqual(response.status_code, 403)
        collector.assert_not_called()

    def test_recent_tasks_uses_repository_dependency(self) -> None:
        app = FastAPI()
        app.include_router(routes_monitor.router, prefix="/api")
        repository = MagicMock(spec=MonitorTaskRepository)
        expected = {
            "items": [{"id": 42, "status": "completed"}],
            "total": 1,
            "page": 3,
            "page_size": 7,
        }
        repository.list_tasks.return_value = expected
        require_admin = MagicMock()
        provide_repository = MagicMock()

        def override_require_admin() -> dict[str, str]:
            require_admin()
            return {"role": "admin"}

        def override_repository():
            provide_repository()
            return repository

        app.dependency_overrides[RequireAdmin] = override_require_admin
        app.dependency_overrides[get_ingestion_task_repository] = override_repository

        response = TestClient(app).get(
            "/api/monitor/tasks",
            params={"page": 3, "page_size": 7},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        require_admin.assert_called_once_with()
        provide_repository.assert_called_once_with()
        repository.list_tasks.assert_called_once_with(3, 7)

    def test_recent_tasks_caps_page_size_at_100(self) -> None:
        app = FastAPI()
        app.include_router(routes_monitor.router, prefix="/api")
        repository = MagicMock(spec=MonitorTaskRepository)
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[get_ingestion_task_repository] = lambda: repository

        for page_size in (0, 101, 100000):
            with self.subTest(page_size=page_size):
                response = TestClient(app).get(
                    "/api/monitor/tasks",
                    params={"page": 1, "page_size": page_size},
                )
                self.assertEqual(response.status_code, 422)
        repository.list_tasks.assert_not_called()

        repository.list_tasks.return_value = {
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 100,
        }
        response = TestClient(app).get(
            "/api/monitor/tasks",
            params={"page": 1, "page_size": 100},
        )
        self.assertEqual(response.status_code, 200)

    def test_recent_error_events_uses_repository_dependency(self) -> None:
        app = FastAPI()
        app.include_router(routes_monitor.router, prefix="/api")
        repository = MagicMock(spec=ErrorEventReader)
        expected = {
            "items": [
                {
                    "id": 7,
                    "occurred_at": "2026-08-12T10:00:00+00:00",
                    "level": "ERROR",
                    "logger_name": "backend.app.core.scheduler",
                    "message": "ingestion failed",
                    "exception_type": "OperationalError",
                    "stack_trace": None,
                }
            ],
            "total": 1,
            "page": 2,
            "page_size": 5,
        }
        repository.list_events.return_value = expected
        require_admin = MagicMock()

        def override_require_admin() -> dict[str, str]:
            require_admin()
            return {"role": "admin"}

        app.dependency_overrides[RequireAdmin] = override_require_admin
        app.dependency_overrides[get_error_event_repository] = lambda: repository

        response = TestClient(app).get(
            "/api/monitor/errors",
            params={"page": 2, "page_size": 5},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        require_admin.assert_called_once_with()
        repository.list_events.assert_called_once_with(2, 5)

    def test_recent_error_events_requires_admin_before_repository_calls(self) -> None:
        app = FastAPI()
        app.include_router(routes_monitor.router, prefix="/api")
        repository = MagicMock(spec=ErrorEventReader)
        app.dependency_overrides[get_error_event_repository] = lambda: repository

        response = TestClient(app).get("/api/monitor/errors")

        self.assertIn(response.status_code, (401, 403))
        repository.list_events.assert_not_called()

    def test_recent_error_events_caps_page_size_at_100(self) -> None:
        app = FastAPI()
        app.include_router(routes_monitor.router, prefix="/api")
        repository = MagicMock(spec=ErrorEventReader)
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[get_error_event_repository] = lambda: repository

        for page_size in (0, 101, 100000):
            with self.subTest(page_size=page_size):
                response = TestClient(app).get(
                    "/api/monitor/errors",
                    params={"page": 1, "page_size": page_size},
                )
                self.assertEqual(response.status_code, 422)
        repository.list_events.assert_not_called()


if __name__ == "__main__":
    unittest.main()
