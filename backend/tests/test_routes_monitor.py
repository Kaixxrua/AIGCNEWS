from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_monitor
from backend.app.api.dependencies import get_mysql_repository
from backend.app.core.auth import RequireAdmin, RequireUser
from backend.app.repositories.task_repository import MonitorTaskRepository


class MonitorRouteTests(unittest.TestCase):
    def test_system_metrics_preserves_no_argument_collector_call(self) -> None:
        app = FastAPI()
        app.include_router(routes_monitor.router, prefix="/api")
        collector = MagicMock(return_value={"uptime_seconds": 1.0})

        def override_require_user() -> dict[str, str]:
            return {"role": "user"}

        app.dependency_overrides[RequireUser] = override_require_user

        with unittest.mock.patch(
            "backend.app.monitoring.metrics.collect_metrics",
            collector,
        ):
            response = TestClient(app).get("/api/monitor/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"uptime_seconds": 1.0})
        collector.assert_called_once_with()

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
        app.dependency_overrides[get_mysql_repository] = override_repository

        response = TestClient(app).get(
            "/api/monitor/tasks",
            params={"page": 3, "page_size": 7},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        require_admin.assert_called_once_with()
        provide_repository.assert_called_once_with()
        repository.list_tasks.assert_called_once_with(3, 7)


if __name__ == "__main__":
    unittest.main()
