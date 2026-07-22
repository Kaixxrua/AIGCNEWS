from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from backend.app.api import dependencies
from backend.app.core.database import DatabaseLifecycle


class DatabaseDependencyTests(unittest.TestCase):
    def test_get_database_returns_application_lifecycle(self) -> None:
        app = FastAPI()
        database = MagicMock(spec=DatabaseLifecycle)
        app.state.database = database
        request = MagicMock(spec=Request)
        request.app = app

        self.assertIs(dependencies.get_database(request), database)

    def test_get_database_fails_when_lifecycle_is_not_configured(self) -> None:
        app = FastAPI()
        request = MagicMock(spec=Request)
        request.app = app

        with self.assertRaisesRegex(
            RuntimeError,
            "Database lifecycle is not configured",
        ):
            dependencies.get_database(request)

    def test_get_mysql_repository_uses_injected_lifecycle(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        repository = MagicMock()

        with patch.object(
            dependencies,
            "MySQLRepository",
            return_value=repository,
        ) as repository_type:
            result = dependencies.get_mysql_repository(database)

        self.assertIs(result, repository)
        repository_type.assert_called_once_with(database=database)

    def test_get_ingestion_task_repository_uses_compatibility_component(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        task_repository = MagicMock()
        repository = MagicMock(ingestion_tasks=task_repository)

        with patch.object(
            dependencies,
            "MySQLRepository",
            return_value=repository,
        ) as repository_type:
            result = dependencies.get_ingestion_task_repository(database)

        self.assertIs(result, task_repository)
        repository_type.assert_called_once_with(database=database)

    def test_task_repository_dependency_can_be_overridden(self) -> None:
        app = FastAPI()
        repository = MagicMock()

        @app.get("/tasks")
        def read_tasks(
            injected=Depends(dependencies.get_ingestion_task_repository),
        ) -> dict[str, bool]:
            return {"overridden": injected is repository}

        app.dependency_overrides[
            dependencies.get_ingestion_task_repository
        ] = lambda: repository

        with patch.object(dependencies, "MySQLRepository") as repository_type:
            response = TestClient(app).get("/tasks")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"overridden": True})
        repository_type.assert_not_called()

    def test_repository_dependency_can_be_overridden(self) -> None:
        app = FastAPI()
        repository = MagicMock()

        @app.get("/repository")
        def read_repository(
            injected=Depends(dependencies.get_mysql_repository),
        ) -> dict[str, bool]:
            return {"overridden": injected is repository}

        app.dependency_overrides[dependencies.get_mysql_repository] = lambda: repository

        with patch.object(dependencies, "MySQLRepository") as repository_type:
            response = TestClient(app).get("/repository")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"overridden": True})
        repository_type.assert_not_called()


if __name__ == "__main__":
    unittest.main()
