from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_ops
from backend.app.api.dependencies import (
    get_ingestion_task_repository,
    get_mysql_repository,
)
from backend.app.core.auth import RequireAdmin
from backend.app.repositories.task_repository import IngestionTaskAdminRepository


class OperationsRouteTests(unittest.TestCase):
    def test_clear_data_uses_separate_task_admin_repository(self) -> None:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        repository = MagicMock()
        repository.clear_all_documents.return_value = 4
        task_repository = MagicMock(spec=IngestionTaskAdminRepository)
        task_repository.clear_all_tasks.return_value = 3
        milvus = MagicMock()
        milvus.drop_collection.return_value = True

        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[get_mysql_repository] = lambda: repository
        app.dependency_overrides[
            get_ingestion_task_repository
        ] = lambda: task_repository

        with patch(
            "backend.app.repositories.milvus_repo.MilvusRepository",
            return_value=milvus,
        ):
            response = TestClient(app).post("/api/ops/clear-data")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "success",
                "message": "已清空 4 条文档、3 条任务记录，Milvus 集合已删除。",
                "deleted_documents": 4,
                "deleted_tasks": 3,
                "milvus_dropped": True,
            },
        )
        repository.clear_all_documents.assert_called_once_with()
        repository.clear_all_tasks.assert_not_called()
        task_repository.clear_all_tasks.assert_called_once_with()
        milvus.drop_collection.assert_called_once_with()

    def test_clear_data_requires_admin_before_deleting(self) -> None:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        repository = MagicMock()
        task_repository = MagicMock(spec=IngestionTaskAdminRepository)

        app.dependency_overrides[get_mysql_repository] = lambda: repository
        app.dependency_overrides[
            get_ingestion_task_repository
        ] = lambda: task_repository

        response = TestClient(app).post("/api/ops/clear-data")

        self.assertIn(response.status_code, (401, 403))
        repository.clear_all_documents.assert_not_called()
        task_repository.clear_all_tasks.assert_not_called()

    def test_clear_data_does_not_report_task_delete_failure_as_success(self) -> None:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        repository = MagicMock()
        repository.clear_all_documents.return_value = 4
        task_repository = MagicMock(spec=IngestionTaskAdminRepository)
        task_repository.clear_all_tasks.side_effect = RuntimeError("delete failed")

        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[get_mysql_repository] = lambda: repository
        app.dependency_overrides[
            get_ingestion_task_repository
        ] = lambda: task_repository

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/api/ops/clear-data")

        self.assertEqual(response.status_code, 500)


if __name__ == "__main__":
    unittest.main()
