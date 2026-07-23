from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_ops
from backend.app.api.dependencies import (
    get_ingestion_task_repository,
    get_mcp_server_config_repository,
    get_mysql_repository,
)
from backend.app.core.auth import RequireAdmin
from backend.app.repositories.mcp_server_repository import McpServerConfigRepository
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

    def test_mcp_server_list_uses_injected_repository_and_redacts_token(self) -> None:
        repository = MagicMock(spec=McpServerConfigRepository)
        repository.list_mcp_server_configs.return_value = [
            self._mcp_row(auth_token="internal-secret", last_tools_json='[{"name":"search"}]')
        ]
        client = self._mcp_client(repository)

        response = client.get("/api/ops/mcp-servers")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertNotIn("auth_token", body["items"][0])
        self.assertTrue(body["items"][0]["auth_token_configured"])
        self.assertEqual(body["items"][0]["tools"], [{"name": "search", "description": ""}])
        repository.list_mcp_server_configs.assert_called_once_with()

    def test_mcp_server_create_forwards_validated_payload_and_maps_duplicate(self) -> None:
        from pymysql.err import IntegrityError

        repository = MagicMock(spec=McpServerConfigRepository)
        repository.create_mcp_server_config.return_value = self._mcp_row(auth_token="new-secret")
        client = self._mcp_client(repository)
        payload = self._mcp_request(auth_token="new-secret")

        response = client.post("/api/ops/mcp-servers", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("auth_token", response.json())
        repository.create_mcp_server_config.assert_called_once_with(
            {
                "server_key": "example",
                "display_name": "Example MCP",
                "description": "",
                "url": "https://example.test/mcp",
                "transport": "streamable_http",
                "auth_type": "bearer",
                "auth_token": "new-secret",
                "clear_auth_token": False,
                "enabled": True,
            }
        )

        repository.create_mcp_server_config.side_effect = IntegrityError()
        duplicate = client.post("/api/ops/mcp-servers", json=payload)
        self.assertEqual(duplicate.status_code, 409)

    def test_mcp_server_update_delete_preserve_missing_mappings(self) -> None:
        repository = MagicMock(spec=McpServerConfigRepository)
        repository.update_mcp_server_config.return_value = None
        repository.delete_mcp_server_config.return_value = False
        client = self._mcp_client(repository)

        update = client.put(
            "/api/ops/mcp-servers/42",
            json=self._mcp_request(auth_token=None, clear_auth_token=True),
        )
        delete = client.delete("/api/ops/mcp-servers/42")

        self.assertEqual(update.status_code, 404)
        self.assertEqual(delete.status_code, 404)
        update_payload = repository.update_mcp_server_config.call_args.args[1]
        self.assertIsNone(update_payload["auth_token"])
        self.assertTrue(update_payload["clear_auth_token"])
        repository.delete_mcp_server_config.assert_called_once_with(42)

    def test_mcp_server_connection_test_uses_internal_token_but_redacts_response(self) -> None:
        repository = MagicMock(spec=McpServerConfigRepository)
        row = self._mcp_row(auth_token="internal-secret")
        updated = self._mcp_row(
            auth_token="internal-secret",
            last_test_status="succeeded",
            last_tools_json='[{"name":"search","description":"搜索"}]',
        )
        repository.get_mcp_server_config.return_value = row
        repository.update_mcp_server_test_result.return_value = updated
        client = self._mcp_client(repository)
        result = {
            "status": "succeeded",
            "message": "ready",
            "tools": [{"name": "search", "description": "搜索"}],
        }

        with patch(
            "backend.app.services.mcp_connection_tester.test_mcp_server_connection",
            return_value=result,
        ) as tester:
            response = client.post("/api/ops/mcp-servers/42/test")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("auth_token", response.json()["server"])
        tester.assert_called_once_with(row)
        repository.update_mcp_server_test_result.assert_called_once_with(42, result)

    def test_mcp_server_routes_require_admin_before_repository_calls(self) -> None:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        repository = MagicMock(spec=McpServerConfigRepository)
        app.dependency_overrides[get_mcp_server_config_repository] = lambda: repository

        response = TestClient(app).get("/api/ops/mcp-servers")

        self.assertIn(response.status_code, (401, 403))
        repository.list_mcp_server_configs.assert_not_called()

    @staticmethod
    def _mcp_client(repository: McpServerConfigRepository) -> TestClient:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[get_mcp_server_config_repository] = lambda: repository
        return TestClient(app)

    @staticmethod
    def _mcp_request(**overrides):
        payload = {
            "server_key": "example",
            "display_name": "Example MCP",
            "url": "https://example.test/mcp",
            "auth_type": "bearer",
            "auth_token": "secret",
        }
        payload.update(overrides)
        return payload

    @staticmethod
    def _mcp_row(**overrides):
        row = {
            "id": 42,
            "server_key": "example",
            "display_name": "Example MCP",
            "description": "",
            "url": "https://example.test/mcp",
            "transport": "streamable_http",
            "auth_type": "bearer",
            "auth_token": None,
            "enabled": 1,
            "last_test_status": "unknown",
            "last_test_message": "",
            "last_test_at": None,
            "last_tools_json": "[]",
            "created_at": None,
            "updated_at": None,
        }
        row.update(overrides)
        return row


if __name__ == "__main__":
    unittest.main()
