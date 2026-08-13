from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_ops, routes_ops_github, routes_ops_mcp, routes_ops_x
from backend.app.api.dependencies import (
    get_briefing_admin_service,
    get_document_repository,
    get_github_project_admin_service,
    get_github_project_crawl_admin_service,
    get_github_project_recommendation_admin_service,
    get_ingestion_task_repository,
    get_mcp_server_config_repository,
    get_operations_runtime,
    get_ops_diagnostics_service,
    get_runtime_provider_admin_service,
    get_runtime_provider_setting_repository,
    get_scheduler_admin_service,
)
from backend.app.core.auth import RequireAdmin
from backend.app.repositories.mcp_server_repository import (
    McpServerConfigConflictError,
    McpServerConfigRepository,
)
from backend.app.repositories.project_write_repository import (
    GitHubProjectEnrichmentRepository,
    GitHubProjectRecommendationRepository,
)
from backend.app.repositories.runtime_provider_repository import (
    RuntimeProviderSettingManager,
)
from backend.app.repositories.task_repository import IngestionTaskAdminRepository
from backend.app.services.github_project_recommendation_admin import (
    GitHubProjectRecommendationAdminService,
)
from backend.app.services.scheduler_admin import SchedulerAdminService


class OperationsRouteTests(unittest.TestCase):
    def test_routes_do_not_use_request_scoped_background_tasks(self) -> None:
        modules = (routes_ops, routes_ops_mcp, routes_ops_x, routes_ops_github)
        for module in modules:
            source = module.__file__
            assert source is not None
            with open(source, encoding="utf-8") as route_file:
                tree = ast.parse(route_file.read())

            imported_names = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in node.names
            }
            referenced_names = {
                node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
            }

            with self.subTest(module=module.__name__):
                self.assertNotIn("BackgroundTasks", imported_names)
                self.assertNotIn("BackgroundTasks", referenced_names)

    def test_generate_all_briefings_queues_injected_service(self) -> None:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        service = MagicMock()
        operations = MagicMock()
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[get_briefing_admin_service] = lambda: service
        app.dependency_overrides[get_operations_runtime] = lambda: operations

        response = TestClient(app).post(
            "/api/ops/briefing/generate-all",
            params={"force_regenerate": "false"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "queued",
                "message": "全维度每日简报生成任务已提交（force_regenerate=False），后台执行中。",
                "task_id": None,
            },
        )
        operations.submit.assert_called_once_with(service.generate_all, False)

    def test_generate_all_briefings_requires_admin_before_queueing(self) -> None:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        service = MagicMock()
        operations = MagicMock()
        app.dependency_overrides[get_briefing_admin_service] = lambda: service
        app.dependency_overrides[get_operations_runtime] = lambda: operations

        response = TestClient(app).post("/api/ops/briefing/generate-all")

        self.assertIn(response.status_code, (401, 403))
        service.generate_all.assert_not_called()
        operations.submit.assert_not_called()

    def test_diagnostics_routes_use_injected_service(self) -> None:
        service = MagicMock()
        service.project_taxonomy.return_value = [
            {
                "slug": "developer-tools",
                "name": "开发工具",
                "children": [{"slug": "code", "name": "代码"}],
            }
        ]
        service.project_catalog_readiness = AsyncMock(
            return_value={"runtime_ready": True}
        )
        service.project_search_shadow_status.return_value = {
            "epoch": "search-v2"
        }
        service.finalize_project_shadow = AsyncMock(
            return_value={
                "search": {
                    "epoch": "search-v2",
                    "lifecycle": "finalized",
                }
            }
        )
        client = self._diagnostics_client(service)

        taxonomy = client.get("/api/ops/project-taxonomy")
        readiness = client.get("/api/ops/project-catalog/readiness")
        shadow = client.get("/api/ops/project-search/shadow-status")
        finalization = client.post("/api/ops/project-shadow/finalize")

        self.assertEqual(taxonomy.status_code, 200)
        self.assertEqual(
            taxonomy.json(),
            {
                "items": [
                    {
                        "slug": "developer-tools",
                        "name": "开发工具",
                        "children": [{"slug": "code", "name": "代码"}],
                    }
                ]
            },
        )
        self.assertEqual(readiness.json(), {"runtime_ready": True})
        self.assertEqual(shadow.json(), {"epoch": "search-v2"})
        self.assertEqual(
            finalization.json(),
            {
                "search": {
                    "epoch": "search-v2",
                    "lifecycle": "finalized",
                }
            },
        )
        service.project_taxonomy.assert_called_once_with()
        service.project_catalog_readiness.assert_awaited_once_with()
        service.project_search_shadow_status.assert_called_once_with()
        service.finalize_project_shadow.assert_awaited_once_with()

    def test_diagnostics_routes_require_admin_before_service_access(self) -> None:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        service = MagicMock()
        app.dependency_overrides[get_ops_diagnostics_service] = lambda: service
        client = TestClient(app)

        responses = (
            client.get("/api/ops/project-taxonomy"),
            client.get("/api/ops/project-catalog/readiness"),
            client.get("/api/ops/project-search/shadow-status"),
            client.post("/api/ops/project-shadow/finalize"),
        )

        self.assertTrue(
            all(response.status_code in (401, 403) for response in responses)
        )
        service.project_taxonomy.assert_not_called()
        service.project_catalog_readiness.assert_not_called()
        service.project_search_shadow_status.assert_not_called()
        service.finalize_project_shadow.assert_not_called()

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
        app.dependency_overrides[get_document_repository] = lambda: repository
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

        app.dependency_overrides[get_document_repository] = lambda: repository
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
        app.dependency_overrides[get_document_repository] = lambda: repository
        app.dependency_overrides[
            get_ingestion_task_repository
        ] = lambda: task_repository

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/api/ops/clear-data")

        self.assertEqual(response.status_code, 500)

    def test_bulk_delete_uses_one_batch_call_and_preserves_response_contract(self) -> None:
        repository = MagicMock()
        repository.delete_documents.return_value = ["x:1", "x:3"]
        client = self._documents_client(repository)

        with patch.object(
            routes_ops, "clear_dashboard_cache_safely", new=AsyncMock()
        ) as clear_cache:
            response = client.post(
                "/api/ops/documents/bulk-delete",
                json={"doc_ids": ["x:1", "x:2", "x:3"]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "success",
                "message": "已删除 2 条文档，1 条未找到",
                "doc_ids": ["x:1", "x:3"],
                "deleted_count": 2,
                "not_found_count": 1,
            },
        )
        # 批量删除走单事务批量方法，不再逐条调 delete_document
        repository.delete_documents.assert_called_once_with(["x:1", "x:2", "x:3"])
        repository.delete_document.assert_not_called()
        clear_cache.assert_awaited_once_with()

    def test_bulk_delete_dedupes_ids_before_batch_delete(self) -> None:
        repository = MagicMock()
        repository.delete_documents.return_value = ["x:1", "x:2"]
        client = self._documents_client(repository)

        with patch.object(routes_ops, "clear_dashboard_cache_safely", new=AsyncMock()):
            response = client.post(
                "/api/ops/documents/bulk-delete",
                json={"doc_ids": ["x:1", "x:1", "x:2"]},
            )

        self.assertEqual(response.status_code, 200)
        repository.delete_documents.assert_called_once_with(["x:1", "x:2"])
        body = response.json()
        self.assertEqual(body["deleted_count"], 2)
        self.assertEqual(body["not_found_count"], 0)

    def test_bulk_delete_reports_batch_failure_as_error(self) -> None:
        repository = MagicMock()
        repository.delete_documents.side_effect = RuntimeError("db down")
        client = self._documents_client(repository, raise_server_exceptions=False)

        with patch.object(routes_ops, "clear_dashboard_cache_safely", new=AsyncMock()):
            response = client.post(
                "/api/ops/documents/bulk-delete",
                json={"doc_ids": ["x:1", "x:2"]},
            )

        self.assertEqual(response.status_code, 500)

    def test_bulk_delete_requires_admin_before_deleting(self) -> None:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        repository = MagicMock()
        app.dependency_overrides[get_document_repository] = lambda: repository

        response = TestClient(app).post(
            "/api/ops/documents/bulk-delete",
            json={"doc_ids": ["x:1"]},
        )

        self.assertIn(response.status_code, (401, 403))
        repository.delete_documents.assert_not_called()

    @staticmethod
    def _documents_client(
        repository: MagicMock,
        *,
        raise_server_exceptions: bool = True,
    ) -> TestClient:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[get_document_repository] = lambda: repository
        return TestClient(app, raise_server_exceptions=raise_server_exceptions)

    def test_provider_config_uses_injected_repository_and_redacts_key(self) -> None:
        repository = MagicMock(spec=RuntimeProviderSettingManager)
        repository.get_runtime_provider_setting.return_value = {
            "provider": "openai",
            "base_url": "https://example.test/v1",
            "api_key": "internal-secret-key",
            "model_name": "example-model",
        }
        client = self._provider_client(repository)

        response = client.get("/api/ops/provider-config")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("api_key", body)
        self.assertTrue(body["api_key_configured"])
        self.assertEqual(body["api_key_masked"], "inte****-key")
        self.assertNotIn("internal-secret-key", response.text)
        repository.get_runtime_provider_setting.assert_called_once_with()

    def test_provider_config_update_forwards_secret_without_exposing_it(self) -> None:
        repository = MagicMock(spec=RuntimeProviderSettingManager)
        repository.upsert_runtime_provider_setting.return_value = {
            "provider": "anthropic",
            "base_url": "https://example.test",
            "api_key": "replacement-secret",
            "model_name": "example-model",
            "reasoning_effort": "high",
        }
        client = self._provider_client(repository)

        response = client.put(
            "/api/ops/provider-config",
            json={
                "provider": "anthropic",
                "base_url": "https://example.test",
                "api_key": "replacement-secret",
                "clear_api_key": False,
                "model_name": "example-model",
                "reasoning_effort": "high",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("api_key", response.json())
        self.assertEqual(response.json()["reasoning_effort"], "high")
        self.assertNotIn("replacement-secret", response.text)
        repository.upsert_runtime_provider_setting.assert_called_once_with(
            "anthropic",
            "https://example.test",
            "replacement-secret",
            False,
            "example-model",
            "high",
        )

    def test_provider_config_update_accepts_custom_reasoning_effort(self) -> None:
        repository = MagicMock(spec=RuntimeProviderSettingManager)
        repository.upsert_runtime_provider_setting.return_value = {
            "provider": "openai",
            "base_url": "",
            "api_key": None,
            "model_name": "",
            "reasoning_effort": "xhigh",
        }
        client = self._provider_client(repository)

        response = client.put(
            "/api/ops/provider-config",
            json={"provider": "openai", "reasoning_effort": " XHigh "},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reasoning_effort"], "xhigh")
        repository.upsert_runtime_provider_setting.assert_called_once_with(
            "openai",
            "",
            None,
            False,
            "",
            "xhigh",
        )

    def test_enrichment_config_get_projects_configured_and_effective_effort(self) -> None:
        repository = MagicMock(spec=RuntimeProviderSettingManager)
        repository.get_runtime_provider_setting.return_value = {
            "provider": "openai",
            "reasoning_effort": "low",
            "enrichment_reasoning_effort": " High ",
        }
        client = self._provider_client(repository)

        response = client.get("/api/ops/github-projects/enrichment-config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"reasoning_effort": "high", "effective_reasoning_effort": "high"},
        )
        repository.get_runtime_provider_setting.assert_called_once_with()

    def test_enrichment_config_update_normalizes_and_round_trips(self) -> None:
        repository = MagicMock(spec=RuntimeProviderSettingManager)
        repository.update_enrichment_reasoning_effort.return_value = {
            "provider": "openai",
            "reasoning_effort": "low",
            "enrichment_reasoning_effort": "minimal",
        }
        client = self._provider_client(repository)

        response = client.put(
            "/api/ops/github-projects/enrichment-config",
            json={"reasoning_effort": " Minimal "},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"reasoning_effort": "minimal", "effective_reasoning_effort": "minimal"},
        )
        repository.update_enrichment_reasoning_effort.assert_called_once_with("minimal")

    def test_provider_config_requires_admin_before_repository_calls(self) -> None:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        repository = MagicMock(spec=RuntimeProviderSettingManager)
        app.dependency_overrides[
            get_runtime_provider_setting_repository
        ] = lambda: repository

        response = TestClient(app).get("/api/ops/provider-config")

        self.assertIn(response.status_code, (401, 403))
        repository.get_runtime_provider_setting.assert_not_called()

    def test_provider_config_test_returns_business_result_with_http_200(self) -> None:
        service = MagicMock()
        service.test_connection = AsyncMock(
            return_value={
                "status": "success",
                "message": "连接正常：openai / example-model 响应耗时 120ms。",
                "provider": "openai",
                "base_url": "https://example.test",
                "model_name": "example-model",
                "latency_ms": 120,
            }
        )
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[get_runtime_provider_admin_service] = lambda: service

        response = TestClient(app).post("/api/ops/provider-config/test")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["latency_ms"], 120)
        service.test_connection.assert_awaited_once_with()

    def test_provider_config_test_failed_result_is_still_http_200(self) -> None:
        service = MagicMock()
        service.test_connection = AsyncMock(
            return_value={
                "status": "failed",
                "message": "连接测试失败（RuntimeError）：请求失败，请检查模型服务配置与网络环境。",
                "provider": "openai",
                "base_url": "https://example.test",
                "model_name": "example-model",
                "latency_ms": None,
            }
        )
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[get_runtime_provider_admin_service] = lambda: service

        response = TestClient(app).post("/api/ops/provider-config/test")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "failed")
        self.assertIsNone(body["latency_ms"])

    def test_provider_config_test_requires_admin(self) -> None:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        service = MagicMock()
        service.test_connection = AsyncMock()
        app.dependency_overrides[get_runtime_provider_admin_service] = lambda: service

        response = TestClient(app).post("/api/ops/provider-config/test")

        self.assertIn(response.status_code, (401, 403))
        service.test_connection.assert_not_called()

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

        repository.create_mcp_server_config.side_effect = McpServerConfigConflictError()
        duplicate = client.post("/api/ops/mcp-servers", json=payload)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(
            duplicate.json(),
            {"detail": "server_key 已存在，请换一个标识"},
        )

    def test_mcp_server_update_maps_duplicate_to_conflict(self) -> None:
        repository = MagicMock(spec=McpServerConfigRepository)
        repository.update_mcp_server_config.side_effect = McpServerConfigConflictError()
        client = self._mcp_client(repository)

        response = client.put(
            "/api/ops/mcp-servers/42",
            json=self._mcp_request(),
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {"detail": "server_key 已存在，请换一个标识"},
        )

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

    def test_project_recommendation_routes_use_injected_repository(self) -> None:
        repository = MagicMock(spec=GitHubProjectRecommendationRepository)
        repository.recommend_github_project.return_value = {
            "repo_id": "repo-1",
            "full_name": "acme/project",
            "is_recommended": True,
        }
        repository.unrecommend_github_project.return_value = {
            "repo_id": "repo-1",
            "full_name": "acme/project",
            "is_recommended": False,
            "removed": True,
        }
        client = self._project_ops_client(recommendations=repository)

        recommended = client.post(
            "/api/ops/github-projects/recommendations",
            json={"repo_id": "repo-1"},
        )
        removed = client.request(
            "DELETE",
            "/api/ops/github-projects/recommendations",
            json={"full_name": "acme/project"},
        )

        self.assertEqual(recommended.status_code, 200)
        self.assertTrue(recommended.json()["is_recommended"])
        self.assertEqual(removed.status_code, 200)
        self.assertTrue(removed.json()["removed"])
        repository.recommend_github_project.assert_called_once_with(
            repo_id="repo-1",
            full_name="",
            recommended_by_user_id=9,
        )
        repository.unrecommend_github_project.assert_called_once_with(
            repo_id=None,
            full_name="acme/project",
        )

    def test_project_enrichment_status_uses_injected_repository(self) -> None:
        repository = MagicMock(spec=GitHubProjectEnrichmentRepository)
        repository.get_github_project_enrichment_status.return_value = {
            "total": 12,
            "enriched": 7,
        }
        client = self._project_ops_client(enrichment=repository)

        response = client.get("/api/ops/github-projects/enrichment-status")

        self.assertEqual(response.status_code, 200)
        # running 由服务层按进程内批处理状态补充，空闲时恒为 False
        self.assertEqual(response.json(), {"total": 12, "enriched": 7, "running": False})
        repository.get_github_project_enrichment_status.assert_called_once_with()

    def test_github_enrich_queues_with_limit_cap_and_concurrency(self) -> None:
        service = MagicMock()
        operations = MagicMock()
        client = self._enrich_client(service, operations)

        response = client.post(
            "/api/ops/github-projects/enrich",
            json={"limit": 700, "concurrency": 5},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "queued")
        self.assertIn("limit=500", body["message"])
        self.assertIn("并发=5", body["message"])
        operations.submit.assert_called_once_with(
            service.enrich, 500, False, False, True, False, 5
        )

    def test_github_enrich_dry_run_forwards_concurrency_inline(self) -> None:
        service = MagicMock()
        service.enrich.return_value = {"status": "dry_run", "candidates": 3}
        operations = MagicMock()
        client = self._enrich_client(service, operations)

        response = client.post(
            "/api/ops/github-projects/enrich",
            json={"limit": 10, "dry_run": True, "concurrency": 3},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "dry_run")
        service.enrich.assert_called_once_with(
            limit=10,
            force=False,
            dry_run=True,
            retry_failed=True,
            refresh_changed=False,
            concurrency=3,
        )
        operations.submit.assert_not_called()

    def test_github_enrich_rejects_out_of_range_concurrency(self) -> None:
        client = self._enrich_client(MagicMock(), MagicMock())

        for invalid in (0, 11):
            response = client.post(
                "/api/ops/github-projects/enrich",
                json={"concurrency": invalid},
            )
            self.assertEqual(response.status_code, 422)

    def test_github_enrich_cancel_signals_running_batch(self) -> None:
        client = self._enrich_client(MagicMock(), MagicMock())

        with patch(
            "backend.app.services.ingestion.github_project_enricher.request_github_enrichment_cancel",
            return_value=True,
        ) as cancel:
            response = client.post("/api/ops/github-projects/enrich-cancel")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "cancelling")
        self.assertIn("终止", body["message"])
        cancel.assert_called_once_with()

    def test_github_enrich_cancel_reports_when_nothing_running(self) -> None:
        client = self._enrich_client(MagicMock(), MagicMock())

        with patch(
            "backend.app.services.ingestion.github_project_enricher.request_github_enrichment_cancel",
            return_value=False,
        ):
            response = client.post("/api/ops/github-projects/enrich-cancel")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "not_running")
        self.assertIn("没有正在运行", body["message"])

    def test_github_crawl_queues_plan_and_returns_channel(self) -> None:
        service = MagicMock()
        operations = MagicMock()
        client = self._crawl_client(service, operations)

        response = client.post(
            "/api/ops/github-projects/crawl",
            json={
                "min_stars": 600,
                "max_stars": 0,
                "created_start": "2025-01-01",
                "created_end": "2026-08-04",
                "limit": 100,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "queued")
        self.assertTrue(body["channel"].startswith("admin_crawl_"))
        self.assertTrue(body["first_seen_after"])
        service.try_acquire_crawl.assert_called_once_with()
        operations.submit.assert_called_once()
        submit_args = operations.submit.call_args.args
        self.assertEqual(submit_args[0], service.crawl_and_enrich)
        plan = submit_args[1]
        self.assertEqual(plan["min_stars"], 600)
        self.assertEqual(plan["max_stars"], 0)
        self.assertEqual(plan["limit"], 100)
        self.assertEqual(plan["created_end"].isoformat(), "2026-08-04")
        self.assertTrue(plan["enrich"])
        service.crawl_dry_run.assert_not_called()

    def test_github_crawl_dry_run_runs_inline_without_submit(self) -> None:
        service = MagicMock()
        service.crawl_dry_run.return_value = {
            "status": "dry_run",
            "shards": {"2026-01-01..2026-01-01": 42},
            "total_available": 42,
        }
        operations = MagicMock()
        client = self._crawl_client(service, operations)

        response = client.post(
            "/api/ops/github-projects/crawl",
            json={
                "dry_run": True,
                "created_start": "2026-01-01",
                "created_end": "2026-01-01",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "dry_run")
        self.assertEqual(body["result"]["total_available"], 42)
        service.crawl_dry_run.assert_called_once()
        service.try_acquire_crawl.assert_not_called()
        operations.submit.assert_not_called()

    def test_github_crawl_returns_conflict_when_lock_held(self) -> None:
        service = MagicMock()
        service.try_acquire_crawl.return_value = False
        operations = MagicMock()
        client = self._crawl_client(service, operations)

        response = client.post("/api/ops/github-projects/crawl", json={})

        self.assertEqual(response.status_code, 409)
        operations.submit.assert_not_called()

    def test_github_crawl_releases_lock_when_runtime_refuses_submit(self) -> None:
        service = MagicMock()
        operations = MagicMock()
        operations.submit.return_value = False
        client = self._crawl_client(service, operations)

        response = client.post("/api/ops/github-projects/crawl", json={})

        self.assertEqual(response.status_code, 503)
        service.release_crawl.assert_called_once_with()

    def test_github_crawl_rejects_invalid_window(self) -> None:
        service = MagicMock()
        operations = MagicMock()
        client = self._crawl_client(service, operations)

        max_below_min = client.post(
            "/api/ops/github-projects/crawl",
            json={"min_stars": 500, "max_stars": 400},
        )
        inverted_dates = client.post(
            "/api/ops/github-projects/crawl",
            json={"created_start": "2026-08-04", "created_end": "2025-01-01"},
        )
        impossible_date = client.post(
            "/api/ops/github-projects/crawl",
            json={"created_start": "2026-13-40"},
        )

        self.assertEqual(max_below_min.status_code, 400)
        self.assertEqual(inverted_dates.status_code, 400)
        self.assertEqual(impossible_date.status_code, 400)
        service.try_acquire_crawl.assert_not_called()
        operations.submit.assert_not_called()

    def test_github_crawl_validates_payload_shape(self) -> None:
        service = MagicMock()
        operations = MagicMock()
        client = self._crawl_client(service, operations)

        negative_stars = client.post(
            "/api/ops/github-projects/crawl", json={"min_stars": -1}
        )
        bad_date_format = client.post(
            "/api/ops/github-projects/crawl", json={"created_start": "2026/01/01"}
        )

        self.assertEqual(negative_stars.status_code, 422)
        self.assertEqual(bad_date_format.status_code, 422)
        service.try_acquire_crawl.assert_not_called()
        operations.submit.assert_not_called()

    def test_github_crawl_routes_require_admin(self) -> None:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        service = MagicMock()
        operations = MagicMock()
        app.dependency_overrides[
            get_github_project_crawl_admin_service
        ] = lambda: service
        app.dependency_overrides[get_operations_runtime] = lambda: operations
        client = TestClient(app)

        crawl = client.post("/api/ops/github-projects/crawl", json={})
        status = client.get("/api/ops/github-projects/crawl/status")

        self.assertIn(crawl.status_code, (401, 403))
        self.assertIn(status.status_code, (401, 403))
        service.try_acquire_crawl.assert_not_called()
        service.crawl_status.assert_not_called()
        operations.submit.assert_not_called()

    def test_github_crawl_status_passthrough_and_maps_value_error(self) -> None:
        service = MagicMock()
        service.crawl_status.return_value = {
            "status": "running",
            "channel": "admin_crawl_x",
            "first_seen_after": "2026-08-04T12:30:15+00:00",
            "task_id": 7,
            "task_status": "running",
            "item_count": 0,
            "error_msg": None,
            "started_at": "2026-08-04T12:30:15+00:00",
            "finished_at": None,
            "candidates_upserted": 10,
            "scope_total": 8,
            "enriched_succeeded": 5,
            "enriched_failed": 1,
        }
        operations = MagicMock()
        client = self._crawl_client(service, operations)

        response = client.get(
            "/api/ops/github-projects/crawl/status",
            params={"channel": "admin_crawl_x"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "running")
        self.assertEqual(body["channel"], "admin_crawl_x")
        self.assertEqual(body["candidates_upserted"], 10)
        self.assertEqual(body["enriched_succeeded"], 5)
        service.crawl_status.assert_called_once_with(
            channel="admin_crawl_x", first_seen_after="", min_stars=None
        )

        response = client.get(
            "/api/ops/github-projects/crawl/status",
            params={"min_stars": 600},
        )
        self.assertEqual(response.status_code, 200)
        service.crawl_status.assert_called_with(
            channel="", first_seen_after="", min_stars=600
        )

        service.crawl_status.side_effect = ValueError("anchor 必须是 ISO 8601")
        bad = client.get(
            "/api/ops/github-projects/crawl/status",
            params={"first_seen_after": "not-a-date"},
        )
        self.assertEqual(bad.status_code, 400)

    @staticmethod
    def _crawl_client(service: MagicMock, operations: MagicMock) -> TestClient:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[
            get_github_project_crawl_admin_service
        ] = lambda: service
        app.dependency_overrides[get_operations_runtime] = lambda: operations
        return TestClient(app)

    @staticmethod
    def _enrich_client(service: MagicMock, operations: MagicMock) -> TestClient:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[
            get_github_project_admin_service
        ] = lambda: service
        app.dependency_overrides[get_operations_runtime] = lambda: operations
        return TestClient(app)

    def test_scheduler_status_preserves_registered_job_projection(self) -> None:
        scheduler = MagicMock()
        scheduler.running = True
        daily_job = MagicMock()
        daily_job.id = "daily"
        daily_job.name = "Daily ingestion"
        daily_job.next_run_time = datetime(2026, 7, 31, 1, 2, tzinfo=timezone.utc)
        daily_job.trigger = "cron[hour='1']"
        paused_job = MagicMock()
        paused_job.id = "paused"
        paused_job.name = "Paused job"
        paused_job.next_run_time = None
        paused_job.trigger = "interval[1:00:00]"
        scheduler.get_jobs.return_value = [daily_job, paused_job]

        response = self._scheduler_client(scheduler=scheduler).get(
            "/api/ops/scheduler/status"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "running": True,
                "jobs": [
                    {
                        "id": "daily",
                        "name": "Daily ingestion",
                        "next_run_time": "2026-07-31T01:02:00+00:00",
                        "trigger": "cron[hour='1']",
                    },
                    {
                        "id": "paused",
                        "name": "Paused job",
                        "next_run_time": None,
                        "trigger": "interval[1:00:00]",
                    },
                ],
                "job_count": 2,
            },
        )
        scheduler.get_jobs.assert_called_once_with()

    def test_scheduler_trigger_reports_missing_job_without_wakeup(self) -> None:
        scheduler = MagicMock()
        scheduler.get_job.return_value = None

        response = self._scheduler_client(scheduler=scheduler).post(
            "/api/ops/scheduler/trigger",
            params={"job_id": "missing"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "error", "message": "Job 'missing' 不存在。"},
        )
        scheduler.get_job.assert_called_once_with("missing")
        scheduler.wakeup.assert_not_called()

    def test_scheduler_trigger_modifies_job_and_wakes_scheduler(self) -> None:
        scheduler = MagicMock()
        job = MagicMock()
        scheduler.get_job.return_value = job

        response = self._scheduler_client(scheduler=scheduler).post(
            "/api/ops/scheduler/trigger",
            params={"job_id": "daily"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "triggered", "message": "Job 'daily' 已触发执行。"},
        )
        # APScheduler 3.x：next_run_time=None 是 pause；立即触发 = 下次点火设为现在
        job.modify.assert_called_once()
        next_run = job.modify.call_args.kwargs["next_run_time"]
        self.assertIsInstance(next_run, datetime)
        self.assertIsNotNone(next_run.tzinfo)
        self.assertLessEqual(
            abs((datetime.now(timezone.utc) - next_run).total_seconds()), 5
        )
        scheduler.wakeup.assert_called_once_with()

    def test_dashboard_cache_clear_uses_all_patterns_and_closes_client(self) -> None:
        redis_client = MagicMock()
        redis_client.keys = AsyncMock(
            side_effect=[
                [b"aigc-cache:dashboard:one"],
                [],
                [b"dashboard:two", b"dashboard:three"],
                [],
            ]
        )
        redis_client.delete = AsyncMock()
        redis_client.aclose = AsyncMock()

        with (
            patch("backend.app.core.redis_client.Redis", return_value=redis_client) as redis_type,
            patch("fastapi_cache.FastAPICache._prefix", "custom:", create=True),
        ):
            response = self._scheduler_client().post(
                "/api/ops/cache/clear-dashboard"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertIn("共删除 3 个 Redis key", response.json()["message"])
        from backend.app.core.config import settings

        redis_type.assert_called_once_with(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            password=settings.redis_password or None,
            decode_responses=False,
        )
        self.assertEqual(
            [call.args[0] for call in redis_client.keys.await_args_list],
            [
                "aigc-cache:dashboard:*",
                "custom:dashboard:*",
                "dashboard:*",
                "*:dashboard:*",
            ],
        )
        self.assertEqual(redis_client.delete.await_count, 2)
        redis_client.aclose.assert_awaited_once_with()

    def test_dashboard_cache_clear_closes_client_when_lookup_fails(self) -> None:
        redis_client = MagicMock()
        redis_client.keys = AsyncMock(side_effect=RuntimeError("redis failed"))
        redis_client.aclose = AsyncMock()

        with patch("backend.app.core.redis_client.Redis", return_value=redis_client):
            with self._scheduler_client(raise_server_exceptions=False) as client:
                response = client.post("/api/ops/cache/clear-dashboard")

        self.assertEqual(response.status_code, 500)
        redis_client.aclose.assert_awaited_once_with()

    def test_scheduler_routes_require_admin_before_scheduler_access(self) -> None:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        service = MagicMock()
        app.dependency_overrides[get_scheduler_admin_service] = lambda: service

        status_response = TestClient(app).get("/api/ops/scheduler/status")
        trigger_response = TestClient(app).post("/api/ops/scheduler/trigger")

        self.assertIn(status_response.status_code, (401, 403))
        self.assertIn(trigger_response.status_code, (401, 403))
        service.status.assert_not_called()
        service.trigger.assert_not_called()

    @staticmethod
    def _diagnostics_client(service: MagicMock) -> TestClient:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[get_ops_diagnostics_service] = lambda: service
        return TestClient(app)

    @staticmethod
    def _scheduler_client(
        *,
        scheduler: MagicMock | None = None,
        raise_server_exceptions: bool = True,
    ) -> TestClient:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        if scheduler is not None:
            app.dependency_overrides[get_scheduler_admin_service] = lambda: (
                SchedulerAdminService(scheduler)
            )
        return TestClient(app, raise_server_exceptions=raise_server_exceptions)

    @staticmethod
    def _project_ops_client(
        *,
        recommendations: GitHubProjectRecommendationRepository | None = None,
        enrichment: GitHubProjectEnrichmentRepository | None = None,
    ) -> TestClient:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        app.dependency_overrides[RequireAdmin] = lambda: {
            "role": "admin",
            "user_id": 9,
        }
        if recommendations is not None or enrichment is not None:
            service = GitHubProjectRecommendationAdminService(
                recommendations or MagicMock(),
                enrichment or MagicMock(),
            )
            app.dependency_overrides[
                get_github_project_recommendation_admin_service
            ] = lambda: service
        return TestClient(app)

    @staticmethod
    def _provider_client(repository: RuntimeProviderSettingManager) -> TestClient:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[
            get_runtime_provider_setting_repository
        ] = lambda: repository
        return TestClient(app)

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
