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
