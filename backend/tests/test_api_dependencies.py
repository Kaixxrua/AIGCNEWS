from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from backend.app.api import dependencies


class DatabaseDependencyTests(unittest.TestCase):
    def test_repository_dependencies_return_composition_root_members(self) -> None:
        repositories = MagicMock()
        mapping = {
            dependencies.get_ingestion_task_repository: "ingestion_tasks",
            dependencies.get_briefing_repository: "briefings",
            dependencies.get_briefing_subscription_repository: "briefing_subscriptions",
            dependencies.get_evaluation_repository: "evaluations",
            dependencies.get_mcp_server_config_repository: "mcp_server_configs",
            dependencies.get_mcp_access_token_repository: "mcp_access_tokens",
            dependencies.get_user_account_repository: "users",
            dependencies.get_conversation_repository: "conversations",
            dependencies.get_document_repository: "documents",
            dependencies.get_error_event_repository: "error_events",
            dependencies.get_papers_repository: "documents",
            dependencies.get_rank_snapshot_repository: "rank_snapshots",
            dependencies.get_runtime_provider_setting_repository: (
                "runtime_provider_settings"
            ),
            dependencies.get_github_project_ingestion_repository: "github_ingestion",
            dependencies.get_github_project_enrichment_repository: "github_enrichment",
            dependencies.get_tool_website_enrichment_repository: (
                "tool_website_enrichment"
            ),
            dependencies.get_user_project_collection_repository: "project_collections",
            dependencies.get_github_project_recommendation_repository: (
                "project_recommendations"
            ),
            dependencies.get_github_project_semantic_source_repository: (
                "github_semantic_sources"
            ),
        }

        for provider, attribute in mapping.items():
            self.assertIs(provider(repositories), getattr(repositories, attribute))

    def test_github_recommendation_admin_service_wraps_ports(self) -> None:
        recommendations = MagicMock()
        enrichment = MagicMock()
        catalog = MagicMock()

        with patch.object(
            dependencies,
            "GitHubProjectRecommendationAdminService",
            return_value=MagicMock(),
        ) as service_type:
            result = dependencies.get_github_project_recommendation_admin_service(
                recommendations,
                enrichment,
                catalog,
            )

        self.assertIs(result, service_type.return_value)
        service_type.assert_called_once_with(recommendations, enrichment, catalog)

    def test_runtime_provider_admin_service_wraps_repository(self) -> None:
        repository = MagicMock()
        runtime = MagicMock(spec=dependencies.ApplicationModelProviderRuntime)

        with patch.object(
            dependencies,
            "RuntimeProviderAdminService",
            return_value=MagicMock(),
        ) as service_type:
            result = dependencies.get_runtime_provider_admin_service(repository, runtime)

        self.assertIs(result, service_type.return_value)
        service_type.assert_called_once_with(
            repository,
            invalidate_models=runtime.invalidate,
        )

    def test_model_provider_runtime_requires_lifespan_setup(self) -> None:
        request = MagicMock(spec=Request)
        app = FastAPI()
        request.app = app

        with self.assertRaisesRegex(
            RuntimeError,
            "Application model provider runtime is not configured",
        ):
            dependencies.get_model_provider_runtime(request)

    def test_mcp_admin_service_wraps_repository_and_connection_tester(self) -> None:
        repository = MagicMock()
        tester = MagicMock()

        with (
            patch.object(
                dependencies,
                "McpAdminService",
                return_value=MagicMock(),
            ) as service_type,
            patch(
                "backend.app.services.mcp_connection_tester.test_mcp_server_connection",
                tester,
            ),
        ):
            result = dependencies.get_mcp_admin_service(repository)

        self.assertIs(result, service_type.return_value)
        service_type.assert_called_once_with(repository, tester)

    def test_briefing_admin_service_wraps_injected_generator(self) -> None:
        briefing = MagicMock()

        with patch.object(
            dependencies,
            "BriefingAdminService",
            return_value=MagicMock(),
        ) as service_type:
            result = dependencies.get_briefing_admin_service(briefing)

        self.assertIs(result, service_type.return_value)
        service_type.assert_called_once_with(briefing)

    def test_ops_diagnostics_service_composes_runtime_dependencies(self) -> None:
        readiness = MagicMock()
        runtime = MagicMock()
        taxonomy = ({"slug": "developer-tools", "name": "开发工具"},)
        request = MagicMock(spec=Request)
        app = FastAPI()
        app.state.project_search_runtime = runtime
        request.app = app

        with (
            patch.object(
                dependencies,
                "OpsDiagnosticsService",
                return_value=MagicMock(),
            ) as service_type,
            patch(
                "backend.app.services.project_catalog_readiness."
                "project_catalog_runtime_readiness",
                readiness,
            ),
            patch(
                "backend.app.domain.project_taxonomy.WEBSITE_TAXONOMY",
                taxonomy,
            ),
            patch(
                "backend.app.core.config.settings."
                "project_search_shadow_shutdown_timeout_seconds",
                4.5,
            ),
        ):
            result = dependencies.get_ops_diagnostics_service(request)

        self.assertIs(result, service_type.return_value)
        service_type.assert_called_once_with(
            readiness=readiness,
            shadow_snapshot=runtime.project_search_shadow_snapshot,
            shadow_finalizer=runtime.finalize_project_search_shadow,
            shadow_shutdown_timeout=4.5,
            website_taxonomy=taxonomy,
        )

    def test_monitoring_dependencies_use_application_owned_runtime(self) -> None:
        runtime = MagicMock()
        request = MagicMock(spec=Request)
        app = FastAPI()
        app.state.monitoring_runtime = runtime
        request.app = app

        self.assertIs(dependencies.get_monitoring_runtime(request), runtime)
        self.assertIs(
            dependencies.get_health_check_service(request),
            runtime.health_checks,
        )
        self.assertIs(
            dependencies.get_readiness_check(request),
            runtime.readiness,
        )

    def test_monitoring_runtime_requires_lifespan_setup(self) -> None:
        request = MagicMock(spec=Request)
        app = FastAPI()
        request.app = app

        with self.assertRaisesRegex(
            RuntimeError,
            "Application monitoring is not configured",
        ):
            dependencies.get_monitoring_runtime(request)

    def test_project_search_runtime_uses_application_owned_runtime(self) -> None:
        runtime = MagicMock()
        request = MagicMock(spec=Request)
        app = FastAPI()
        app.state.project_search_runtime = runtime
        request.app = app

        self.assertIs(dependencies.get_project_search_runtime(request), runtime)

    def test_project_search_runtime_requires_lifespan_setup(self) -> None:
        request = MagicMock(spec=Request)
        app = FastAPI()
        request.app = app

        with self.assertRaisesRegex(
            RuntimeError,
            "Project search runtime is not configured",
        ):
            dependencies.get_project_search_runtime(request)

    def test_operations_runtime_uses_application_owned_runtime(self) -> None:
        runtime = dependencies.ApplicationOperationsRuntime()
        request = MagicMock(spec=Request)
        app = FastAPI()
        app.state.operations_runtime = runtime
        request.app = app

        self.assertIs(dependencies.get_operations_runtime(request), runtime)

    def test_operations_runtime_requires_lifespan_setup(self) -> None:
        request = MagicMock(spec=Request)
        app = FastAPI()
        request.app = app

        with self.assertRaisesRegex(
            RuntimeError,
            "Application operations runtime is not configured",
        ):
            dependencies.get_operations_runtime(request)

    def test_daily_briefing_service_binds_saved_notifier_with_runtime(self) -> None:
        runtime = dependencies.ApplicationOperationsRuntime()
        redis_sentinel = object()
        notifier_sentinel = object()
        request = MagicMock(spec=Request)
        app = FastAPI()
        app.state.operations_runtime = runtime
        app.state.redis = redis_sentinel
        request.app = app
        repositories = MagicMock()

        with (
            patch.object(
                dependencies,
                "build_briefing_saved_notifier",
                return_value=notifier_sentinel,
            ) as build,
            patch.object(
                dependencies, "provide_daily_briefing_service"
            ) as provide,
        ):
            service = dependencies.get_daily_briefing_service(
                request, repositories=repositories
            )

        build.assert_called_once_with(
            repositories, operations=runtime, redis_client=redis_sentinel
        )
        provide.assert_called_once_with(
            repositories=repositories, briefing_saved=notifier_sentinel
        )
        self.assertIs(service, provide.return_value)

    def test_daily_briefing_service_degrades_without_operations_runtime(self) -> None:
        # 补发是次功能：运行时缺失时降级为不挂通知，简报生成主链路不受影响。
        request = MagicMock(spec=Request)
        app = FastAPI()
        request.app = app
        repositories = MagicMock()

        with (
            patch.object(dependencies, "build_briefing_saved_notifier") as build,
            patch.object(
                dependencies, "provide_daily_briefing_service"
            ) as provide,
        ):
            dependencies.get_daily_briefing_service(request, repositories=repositories)

        build.assert_not_called()
        provide.assert_called_once_with(repositories=repositories, briefing_saved=None)

    def test_scheduler_admin_service_uses_application_owned_runtime(self) -> None:
        scheduler_control = MagicMock()
        request = MagicMock(spec=Request)
        app = FastAPI()
        app.state.scheduler_runtime = MagicMock(scheduler=scheduler_control)
        request.app = app

        with patch.object(
            dependencies,
            "SchedulerAdminService",
            return_value=MagicMock(),
        ) as service_type:
            result = dependencies.get_scheduler_admin_service(request)

        self.assertIs(result, service_type.return_value)
        service_type.assert_called_once_with(scheduler_control)

    def test_scheduler_admin_service_requires_lifespan_setup(self) -> None:
        request = MagicMock(spec=Request)
        app = FastAPI()
        request.app = app

        with self.assertRaisesRegex(
            RuntimeError,
            "Application scheduler is not configured",
        ):
            dependencies.get_scheduler_admin_service(request)

    def test_conversation_service_wraps_injected_repository(self) -> None:
        repository = MagicMock()

        with patch.object(
            dependencies,
            "ConversationService",
            return_value=MagicMock(),
        ) as service_type:
            result = dependencies.get_conversation_service(repository)

        self.assertIs(result, service_type.return_value)
        service_type.assert_called_once_with(repository)

    def test_get_application_repositories_returns_composition_root(self) -> None:
        app = FastAPI()
        repositories = MagicMock()
        app.state.application_repositories = repositories
        request = MagicMock(spec=Request)
        request.app = app

        self.assertIs(
            dependencies.get_application_repositories(request), repositories
        )

    def test_get_application_repositories_requires_lifespan_setup(self) -> None:
        app = FastAPI()
        request = MagicMock(spec=Request)
        request.app = app

        with self.assertRaisesRegex(
            RuntimeError, "Application repositories are not configured"
        ):
            dependencies.get_application_repositories(request)

    def test_get_pdf_relay_builds_httpx_adapter(self) -> None:
        relay = MagicMock()
        with patch.object(dependencies, "HttpxPdfRelay", return_value=relay) as relay_type:
            result = dependencies.get_pdf_relay()
        self.assertIs(result, relay)
        relay_type.assert_called_once_with()

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

        response = TestClient(app).get("/tasks")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"overridden": True})

    def test_briefing_repository_dependency_can_be_overridden(self) -> None:
        app = FastAPI()
        repository = MagicMock()

        @app.get("/briefings")
        def read_briefings(
            injected=Depends(dependencies.get_briefing_repository),
        ) -> dict[str, bool]:
            return {"overridden": injected is repository}

        app.dependency_overrides[
            dependencies.get_briefing_repository
        ] = lambda: repository

        response = TestClient(app).get("/briefings")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"overridden": True})

    def test_briefing_subscription_dependency_can_be_overridden(self) -> None:
        app = FastAPI()
        repository = MagicMock()

        @app.get("/briefing-subscriptions")
        def read_subscriptions(
            injected=Depends(dependencies.get_briefing_subscription_repository),
        ) -> dict[str, bool]:
            return {"overridden": injected is repository}

        app.dependency_overrides[
            dependencies.get_briefing_subscription_repository
        ] = lambda: repository

        response = TestClient(app).get("/briefing-subscriptions")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"overridden": True})

    def test_evaluation_repository_dependency_can_be_overridden(self) -> None:
        app = FastAPI()
        repository = MagicMock()

        @app.get("/evaluations")
        def read_evaluations(
            injected=Depends(dependencies.get_evaluation_repository),
        ) -> dict[str, bool]:
            return {"overridden": injected is repository}

        app.dependency_overrides[
            dependencies.get_evaluation_repository
        ] = lambda: repository

        response = TestClient(app).get("/evaluations")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"overridden": True})

    def test_mcp_server_config_dependency_can_be_overridden(self) -> None:
        app = FastAPI()
        repository = MagicMock()

        @app.get("/mcp-server-configs")
        def read_mcp_server_configs(
            injected=Depends(dependencies.get_mcp_server_config_repository),
        ) -> dict[str, bool]:
            return {"overridden": injected is repository}

        app.dependency_overrides[
            dependencies.get_mcp_server_config_repository
        ] = lambda: repository

        response = TestClient(app).get("/mcp-server-configs")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"overridden": True})

    def test_user_account_dependency_can_be_overridden(self) -> None:
        app = FastAPI()
        repository = MagicMock()

        @app.get("/user-accounts")
        def read_user_accounts(
            injected=Depends(dependencies.get_user_account_repository),
        ) -> dict[str, bool]:
            return {"overridden": injected is repository}

        app.dependency_overrides[
            dependencies.get_user_account_repository
        ] = lambda: repository

        response = TestClient(app).get("/user-accounts")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"overridden": True})

    def test_document_dependency_can_be_overridden(self) -> None:
        app = FastAPI()
        repository = MagicMock()

        @app.get("/documents")
        def read_documents(
            injected=Depends(dependencies.get_document_repository),
        ) -> dict[str, bool]:
            return {"overridden": injected is repository}

        app.dependency_overrides[
            dependencies.get_document_repository
        ] = lambda: repository

        response = TestClient(app).get("/documents")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"overridden": True})

    def test_runtime_provider_dependency_can_be_overridden(self) -> None:
        app = FastAPI()
        repository = MagicMock()

        @app.get("/runtime-provider")
        def read_runtime_provider(
            injected=Depends(dependencies.get_runtime_provider_setting_repository),
        ) -> dict[str, bool]:
            return {"overridden": injected is repository}

        app.dependency_overrides[
            dependencies.get_runtime_provider_setting_repository
        ] = lambda: repository

        response = TestClient(app).get("/runtime-provider")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"overridden": True})


if __name__ == "__main__":
    unittest.main()
