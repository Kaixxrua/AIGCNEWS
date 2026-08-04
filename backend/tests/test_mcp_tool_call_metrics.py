from __future__ import annotations

import json
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_mcp
from backend.app.api.dependencies import (
    get_application_repositories,
    get_briefing_repository,
    get_project_search_runtime,
)
from backend.app.core.auth import get_mcp_access_token_authenticator
from backend.app.monitoring import metrics as monitor_metrics
from backend.app.monitoring.mcp_tools import JsonMcpToolCallStore, McpToolCallMetrics
from backend.app.repositories.briefing_repository import BriefingReader
from backend.app.repositories.document_repository import DocumentStatisticsReader
from backend.app.repositories.evaluation_repository import EvaluationSummaryReader
from backend.app.repositories.task_repository import RecentTaskReader
from backend.app.services.mcp.inbound import application, context, tools


class McpToolCallMetricsUnitTests(unittest.TestCase):
    def test_snapshot_starts_empty_with_parseable_since(self) -> None:
        snapshot = McpToolCallMetrics().snapshot()

        self.assertEqual(snapshot["total_calls"], 0)
        self.assertEqual(snapshot["tools"], {})
        datetime.fromisoformat(snapshot["since"])

    def test_record_accumulates_counts_and_last_called_per_tool(self) -> None:
        metrics = McpToolCallMetrics()

        metrics.record("get_project_library")
        metrics.record("search_github_ai_projects")
        metrics.record("get_project_library")

        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["total_calls"], 3)
        self.assertEqual(
            list(snapshot["tools"]),
            ["get_project_library", "search_github_ai_projects"],
        )
        self.assertEqual(snapshot["tools"]["get_project_library"]["calls"], 2)
        self.assertEqual(snapshot["tools"]["search_github_ai_projects"]["calls"], 1)
        for entry in snapshot["tools"].values():
            datetime.fromisoformat(entry["last_called_at"])

    def test_instances_are_isolated(self) -> None:
        first = McpToolCallMetrics()
        second = McpToolCallMetrics()

        first.record("get_top_items")

        self.assertEqual(second.snapshot()["total_calls"], 0)


class McpToolCallPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "nested" / "mcp_tool_calls.json"
        self.store = JsonMcpToolCallStore(str(self.path))

    def test_new_instance_recovers_counts_and_since_across_restart(self) -> None:
        first = McpToolCallMetrics(store=self.store)
        first.record("get_project_library")
        first.record("search_github_ai_projects")
        first.record("get_project_library")
        original_since = first.snapshot()["since"]

        restarted = McpToolCallMetrics(store=self.store)
        snapshot = restarted.snapshot()

        self.assertEqual(snapshot["total_calls"], 3)
        self.assertEqual(snapshot["tools"]["get_project_library"]["calls"], 2)
        self.assertEqual(
            snapshot["tools"]["search_github_ai_projects"]["calls"], 1
        )
        self.assertEqual(snapshot["since"], original_since)

        restarted.record("get_project_library")
        self.assertEqual(
            restarted.snapshot()["tools"]["get_project_library"]["calls"], 3
        )

    def test_persisted_file_matches_snapshot_shape_without_tmp_leftover(self) -> None:
        metrics = McpToolCallMetrics(store=self.store)
        metrics.record("search_papers")

        persisted = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(set(persisted), {"since", "total_calls", "tools"})
        self.assertEqual(persisted["total_calls"], 1)
        self.assertEqual(persisted["tools"]["search_papers"]["calls"], 1)
        datetime.fromisoformat(persisted["since"])
        datetime.fromisoformat(
            persisted["tools"]["search_papers"]["last_called_at"]
        )
        self.assertFalse(self.path.with_name(self.path.name + ".tmp").exists())

    def test_missing_file_starts_empty(self) -> None:
        metrics = McpToolCallMetrics(store=self.store)

        self.assertEqual(metrics.snapshot()["total_calls"], 0)
        self.assertFalse(self.path.exists())

    def test_corrupt_file_starts_empty_and_recovers_on_record(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json", encoding="utf-8")
        metrics = McpToolCallMetrics(store=self.store)

        self.assertEqual(metrics.snapshot()["total_calls"], 0)

        metrics.record("get_top_items")
        persisted = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["tools"]["get_top_items"]["calls"], 1)

    def test_invalid_entries_are_skipped_on_load(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            json.dumps(
                {
                    "since": "2026-08-04T00:00:00+00:00",
                    "total_calls": 99,
                    "tools": {
                        "valid_tool": {
                            "calls": 2,
                            "last_called_at": "2026-08-04T01:00:00+00:00",
                        },
                        "zero_calls": {
                            "calls": 0,
                            "last_called_at": "2026-08-04T01:00:00+00:00",
                        },
                        "bad_timestamp": {"calls": 5, "last_called_at": "n/a"},
                        "not_a_mapping": "oops",
                    },
                }
            ),
            encoding="utf-8",
        )
        metrics = McpToolCallMetrics(store=self.store)

        snapshot = metrics.snapshot()
        self.assertEqual(list(snapshot["tools"]), ["valid_tool"])
        self.assertEqual(snapshot["total_calls"], 2)
        self.assertEqual(snapshot["since"], "2026-08-04T00:00:00+00:00")

    def test_save_failure_does_not_break_record(self) -> None:
        failing_store = MagicMock()
        failing_store.load.return_value = None
        failing_store.save.side_effect = OSError("disk full")
        metrics = McpToolCallMetrics(store=failing_store)

        with self.assertLogs("backend.app.monitoring.mcp_tools", level="ERROR"):
            metrics.record("get_project_library")

        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["total_calls"], 1)
        self.assertEqual(snapshot["tools"]["get_project_library"]["calls"], 1)

    def test_snapshot_does_not_write_to_store(self) -> None:
        metrics = McpToolCallMetrics(store=self.store)

        metrics.snapshot()

        self.assertFalse(self.path.exists())


class McpToolCallDispatchTests(unittest.IsolatedAsyncioTestCase):
    def _build_application(
        self, tool_call_metrics: McpToolCallMetrics
    ) -> application.McpProtocolApplication:
        dependencies = application.McpProtocolDependencies(
            authorization=context.McpAuthorizationContext(None),
            tools=tools.McpToolContext(
                user=None,
                documents=MagicMock(),
                papers=MagicMock(),
                rank_snapshots=MagicMock(),
                project_collection=MagicMock(),
                request=MagicMock(),
            ),
            briefing_repository=MagicMock(),
            session_transport=context.McpSessionTransport(),
            tool_call_metrics=tool_call_metrics,
        )
        return application.McpProtocolApplication(dependencies)

    async def _dispatch(
        self,
        app: application.McpProtocolApplication,
        method: str,
        params: dict | None = None,
    ) -> application.McpProtocolResponse:
        inbound = context.McpInboundRequest(
            request_id=1,
            method=method,
            params=params or {},
            has_id=True,
        )
        return await app.dispatch(inbound)

    async def test_tools_call_records_known_tool_attempt(self) -> None:
        metrics = McpToolCallMetrics()
        app = self._build_application(metrics)

        response = await self._dispatch(
            app,
            "tools/call",
            {"name": "search_my_project_favorites", "arguments": {}},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("result", response.body)
        snapshot = metrics.snapshot()
        self.assertEqual(list(snapshot["tools"]), ["search_my_project_favorites"])
        self.assertEqual(
            snapshot["tools"]["search_my_project_favorites"]["calls"], 1
        )

    async def test_tools_call_records_unknown_tool_attempt(self) -> None:
        metrics = McpToolCallMetrics()
        app = self._build_application(metrics)

        response = await self._dispatch(
            app,
            "tools/call",
            {"name": "definitely_unknown_tool", "arguments": {}},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(metrics.snapshot()["total_calls"], 1)
        self.assertEqual(
            metrics.snapshot()["tools"]["definitely_unknown_tool"]["calls"], 1
        )

    async def test_tools_call_without_name_does_not_record(self) -> None:
        metrics = McpToolCallMetrics()
        app = self._build_application(metrics)

        response = await self._dispatch(app, "tools/call", {"arguments": {}})

        self.assertEqual(
            response.body["error"],
            {"code": -32602, "message": "tools/call params.name is required"},
        )
        self.assertEqual(metrics.snapshot()["total_calls"], 0)

    async def test_non_tool_methods_do_not_record(self) -> None:
        metrics = McpToolCallMetrics()
        app = self._build_application(metrics)

        await self._dispatch(app, "initialize")
        await self._dispatch(app, "tools/list")
        await self._dispatch(app, "resources/list")

        self.assertEqual(metrics.snapshot()["total_calls"], 0)


class McpToolCallRouteWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        self.briefing_repository = MagicMock()
        self.token_repository = MagicMock()
        self.project_search_runtime = MagicMock()
        self.project_search_runtime.search_projects = AsyncMock()
        self.repositories = types.SimpleNamespace(
            documents=MagicMock(),
            rank_snapshots=MagicMock(),
            project_collections=MagicMock(),
        )
        app.dependency_overrides[get_briefing_repository] = (
            lambda: self.briefing_repository
        )
        app.dependency_overrides[get_application_repositories] = (
            lambda: self.repositories
        )
        app.dependency_overrides[get_project_search_runtime] = (
            lambda: self.project_search_runtime
        )
        app.dependency_overrides[get_mcp_access_token_authenticator] = (
            lambda: self.token_repository
        )
        app.include_router(routes_mcp.router, prefix="/api")
        self.client = TestClient(app)

    def test_route_records_tool_calls_into_shared_singleton(self) -> None:
        isolated = McpToolCallMetrics()

        with patch.object(routes_mcp, "MCP_TOOL_CALL_METRICS", isolated):
            response = self.client.post(
                "/api/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {"name": "get_project_library", "arguments": {}},
                },
            )

        self.assertEqual(response.status_code, 200)
        snapshot = isolated.snapshot()
        self.assertEqual(snapshot["total_calls"], 1)
        self.assertEqual(snapshot["tools"]["get_project_library"]["calls"], 1)


class CollectMetricsMcpToolCallsTests(unittest.TestCase):
    def _readers(self) -> dict:
        task_reader = MagicMock(spec=RecentTaskReader)
        task_reader.get_recent_tasks.return_value = []
        evaluation_reader = MagicMock(spec=EvaluationSummaryReader)
        evaluation_reader.get_eval_summary.return_value = {}
        document_statistics = MagicMock(spec=DocumentStatisticsReader)
        document_statistics.get_document_count.return_value = 1
        briefing_reader = MagicMock(spec=BriefingReader)
        briefing_reader.list_briefings.return_value = []
        return {
            "task_reader": task_reader,
            "evaluation_reader": evaluation_reader,
            "document_statistics": document_statistics,
            "briefing_reader": briefing_reader,
        }

    def test_collect_metrics_includes_injected_mcp_tool_calls(self) -> None:
        tool_calls = McpToolCallMetrics()
        tool_calls.record("get_project_library")

        result = monitor_metrics.collect_metrics(
            **self._readers(), mcp_tool_calls=tool_calls
        )

        section = result["mcp_tool_calls"]
        self.assertEqual(section["total_calls"], 1)
        self.assertEqual(section["tools"]["get_project_library"]["calls"], 1)
        datetime.fromisoformat(section["since"])

    def test_collect_metrics_defaults_to_shared_singleton(self) -> None:
        isolated = McpToolCallMetrics()
        isolated.record("search_papers")

        with patch.object(monitor_metrics, "MCP_TOOL_CALL_METRICS", isolated):
            result = monitor_metrics.collect_metrics(**self._readers())

        self.assertEqual(result["mcp_tool_calls"]["total_calls"], 1)
        self.assertEqual(
            result["mcp_tool_calls"]["tools"]["search_papers"]["calls"], 1
        )


if __name__ == "__main__":
    unittest.main()
