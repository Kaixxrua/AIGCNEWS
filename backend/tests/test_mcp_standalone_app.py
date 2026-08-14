"""独立 MCP 进程（mcp_main.app）的契约测试。

锁定两件事：
1. 与主进程（main.app）的 MCP wire 行为逐字节一致（initialize/tools-list/
   通知 204/限流 429）——拆进程不许改协议行为；
2. 挂载面收窄——瘦应用只暴露 /api/mcp 与探活/版本端点，REST/管理/文档
   路由一律 404（攻击面最小化是拆进程的目标之一，需契约防回归）。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main as main_module, mcp_main
from backend.app.api.dependencies import (
    get_application_repositories,
    get_briefing_repository,
    get_project_search_runtime,
)
from backend.app.core.auth import OptionalMcpUser
from backend.app.services.mcp.inbound import rate_limit as mcp_rate_limit
from backend.app.services.mcp.inbound.catalog import (
    _PRIVATE_MCP_TOOLS,
    MCP_PROTOCOL_VERSION,
    MCP_SERVER_NAME,
    MCP_SERVER_VERSION,
    MCP_TOOLS,
)
from backend.app.services.mcp.inbound.rate_limit import (
    MCP_JSONRPC_RATE_LIMITED,
    MCP_RATE_LIMIT_WINDOW_SECONDS,
)
from backend.tests.test_email_service_contracts import FakeRedis

SERVER_JSON = Path(__file__).resolve().parents[2] / "server.json"


class _StubRepositories:
    documents = None
    rank_snapshots = None
    project_collections = None


def _build_client(app) -> TestClient:
    """与 test_mcp_inbound_rate_limit 同套路：依赖覆盖 + 手动注入 app.state，
    不跑 lifespan（避免触真实 PostgreSQL/Redis）。"""
    app.dependency_overrides[OptionalMcpUser] = lambda: None
    app.dependency_overrides[get_application_repositories] = (
        lambda: _StubRepositories()
    )
    app.dependency_overrides[get_briefing_repository] = lambda: None
    app.dependency_overrides[get_project_search_runtime] = lambda: SimpleNamespace(
        search_projects=None
    )
    return TestClient(app, raise_server_exceptions=False)


class McpStandaloneWireParityTests(unittest.TestCase):
    """瘦应用与主应用的 MCP 端点行为一致（同一 router，双倍证据）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mcp_client = _build_client(mcp_main.app)
        cls.main_client = _build_client(main_module.app)

    @staticmethod
    def _initialize(client: TestClient):
        return client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )

    def test_initialize_handshake_matches_main_app_byte_for_byte(self) -> None:
        mcp_response = self._initialize(self.mcp_client)
        main_response = self._initialize(self.main_client)

        self.assertEqual(mcp_response.status_code, 200)
        # 会话 id 每次新生成，逐请求合法漂移，剔除后响应体必须逐字节一致
        self.assertEqual(mcp_response.json(), main_response.json())
        result = mcp_response.json()["result"]
        self.assertEqual(result["protocolVersion"], MCP_PROTOCOL_VERSION)
        self.assertEqual(
            result["serverInfo"],
            {"name": MCP_SERVER_NAME, "version": MCP_SERVER_VERSION},
        )
        self.assertIn("mcp-session-id", mcp_response.headers)
        self.assertEqual(
            mcp_response.headers["mcp-protocol-version"], MCP_PROTOCOL_VERSION
        )

    def test_notification_returns_204_in_both_apps(self) -> None:
        payload = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        for client in (self.mcp_client, self.main_client):
            response = client.post("/api/mcp", json=payload)
            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.content, b"")

    def test_tools_list_matches_main_app_and_excludes_private_tools(self) -> None:
        payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        mcp_response = self.mcp_client.post("/api/mcp", json=payload)
        main_response = self.main_client.post("/api/mcp", json=payload)

        self.assertEqual(mcp_response.json(), main_response.json())
        tools = mcp_response.json()["result"]["tools"]
        self.assertEqual(len(tools), len(MCP_TOOLS))
        private_names = {tool["name"] for tool in _PRIVATE_MCP_TOOLS}
        self.assertFalse(private_names & {tool["name"] for tool in tools})

    def test_rate_limit_429_projection_matches_main_app(self) -> None:
        redis = FakeRedis()
        self.mcp_client.app.state.redis = redis
        self.main_client.app.state.redis = redis
        self.addCleanup(setattr, self.mcp_client.app.state, "redis", None)
        self.addCleanup(setattr, self.main_client.app.state, "redis", None)

        def tool_call(request_id: int) -> dict:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": "no_such_tool", "arguments": {}},
            }

        with patch.object(mcp_rate_limit, "MCP_ANONYMOUS_TOOL_CALL_LIMIT", 1):
            first = self.mcp_client.post("/api/mcp", json=tool_call(1))
            self.assertEqual(first.status_code, 200)
            for client in (self.mcp_client, self.main_client):
                response = client.post("/api/mcp", json=tool_call(2))
                self.assertEqual(response.status_code, 429)
                self.assertEqual(
                    response.headers["Retry-After"],
                    str(MCP_RATE_LIMIT_WINDOW_SECONDS),
                )
                payload = response.json()
                self.assertEqual(payload["id"], 2)
                self.assertEqual(
                    payload["error"]["code"], MCP_JSONRPC_RATE_LIMITED
                )

    def test_version_endpoint_matches_server_json_and_main_app(self) -> None:
        document = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
        for client in (self.mcp_client, self.main_client):
            response = client.get("/api/version")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {"name": "aigc-radar", "version": document["version"]},
            )


class McpStandaloneSurfaceTests(unittest.TestCase):
    """瘦应用挂载面收窄契约：只暴露 MCP 端点与探活/版本。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = _build_client(mcp_main.app)

    def test_mcp_endpoint_is_served(self) -> None:
        response = self.client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        self.assertEqual(response.status_code, 200)

    def test_probes_are_served(self) -> None:
        self.assertEqual(self.client.get("/api/live").status_code, 200)
        self.assertEqual(self.client.get("/api/version").status_code, 200)
        # lifespan 未运行（TestClient 非上下文管理器用法），monitoring runtime
        # 缺失时必须 503 而非 500/200——探活失败语义对齐主进程
        self.assertEqual(self.client.get("/api/ready").status_code, 503)

    def test_rest_and_admin_routes_are_not_mounted(self) -> None:
        for path in (
            "/api/monitor/health",
            "/api/monitor/tasks",
            "/api/auth/login",
            "/api/dashboard",
            "/api/github-projects",
            "/api/ops/status",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_interactive_docs_are_never_exposed(self) -> None:
        for path in ("/docs", "/redoc", "/openapi.json"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


if __name__ == "__main__":
    unittest.main()
