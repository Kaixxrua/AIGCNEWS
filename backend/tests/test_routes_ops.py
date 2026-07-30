from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_ops
from backend.app.api.dependencies import (
    get_dashboard_cache_admin_service,
    get_document_repository,
    get_github_project_enrichment_repository,
    get_github_project_recommendation_repository,
    get_ingestion_task_repository,
    get_mcp_server_config_repository,
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
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("api_key", response.json())
        self.assertNotIn("replacement-secret", response.text)
        repository.upsert_runtime_provider_setting.assert_called_once_with(
            "anthropic",
            "https://example.test",
            "replacement-secret",
            False,
            "example-model",
        )

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
        self.assertEqual(response.json(), {"total": 12, "enriched": 7})
        repository.get_github_project_enrichment_status.assert_called_once_with()

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

        with patch("backend.app.core.scheduler.get_scheduler", return_value=scheduler):
            response = self._scheduler_client().get("/api/ops/scheduler/status")

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

        with patch("backend.app.core.scheduler.get_scheduler", return_value=scheduler):
            response = self._scheduler_client().post(
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

        with patch("backend.app.core.scheduler.get_scheduler", return_value=scheduler):
            response = self._scheduler_client().post(
                "/api/ops/scheduler/trigger",
                params={"job_id": "daily"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "triggered", "message": "Job 'daily' 已触发执行。"},
        )
        job.modify.assert_called_once_with(next_run_time=None)
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
            patch("redis.asyncio.Redis", return_value=redis_client) as redis_type,
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

        with patch("redis.asyncio.Redis", return_value=redis_client):
            with self._scheduler_client(raise_server_exceptions=False) as client:
                response = client.post("/api/ops/cache/clear-dashboard")

        self.assertEqual(response.status_code, 500)
        redis_client.aclose.assert_awaited_once_with()

    def test_scheduler_routes_require_admin_before_scheduler_access(self) -> None:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")

        with patch("backend.app.core.scheduler.get_scheduler") as get_scheduler:
            status_response = TestClient(app).get("/api/ops/scheduler/status")
            trigger_response = TestClient(app).post("/api/ops/scheduler/trigger")

        self.assertIn(status_response.status_code, (401, 403))
        self.assertIn(trigger_response.status_code, (401, 403))
        get_scheduler.assert_not_called()

    @staticmethod
    def _scheduler_client(*, raise_server_exceptions: bool = True) -> TestClient:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
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
        if recommendations is not None:
            app.dependency_overrides[
                get_github_project_recommendation_repository
            ] = lambda: recommendations
        if enrichment is not None:
            app.dependency_overrides[
                get_github_project_enrichment_repository
            ] = lambda: enrichment
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
