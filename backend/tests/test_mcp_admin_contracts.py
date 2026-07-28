from __future__ import annotations

import json
import unittest
from collections.abc import Iterable
from unittest.mock import MagicMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_ops
from backend.app.api.dependencies import get_mcp_server_config_repository
from backend.app.core.auth import RequireAdmin
from backend.app.repositories.mcp_server_repository import McpServerConfigRepository
from backend.app.services import mcp_connection_tester as tester

PUBLIC_IP = "8.8.8.8"


def _resolver(_hostname: str) -> Iterable[str]:
    return [PUBLIC_IP]


def _row(**overrides):
    row = {
        "id": 42,
        "server_key": "example",
        "display_name": "Example MCP",
        "description": "",
        "url": "https://mcp.example/rpc",
        "transport": "streamable_http",
        "auth_type": "bearer",
        "auth_token": "internal-secret-token",
        "enabled": True,
        "last_test_status": "unknown",
        "last_test_message": "",
        "last_tools_json": "[]",
        "last_test_at": None,
        "created_at": None,
        "updated_at": None,
    }
    row.update(overrides)
    return row


class McpAdminRouteContracts(unittest.TestCase):
    @staticmethod
    def _client(repository: McpServerConfigRepository) -> TestClient:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[get_mcp_server_config_repository] = lambda: repository
        return TestClient(app)

    def test_crud_responses_never_expose_internal_bearer_token(self) -> None:
        secret = "internal-secret-token"
        repository = MagicMock(spec=McpServerConfigRepository)
        repository.list_mcp_server_configs.return_value = [_row(auth_token=secret)]
        repository.create_mcp_server_config.return_value = _row(auth_token=secret)
        repository.update_mcp_server_config.return_value = _row(auth_token=secret)
        client = self._client(repository)

        responses = [
            client.get("/api/ops/mcp-servers"),
            client.post(
                "/api/ops/mcp-servers",
                json={
                    "server_key": "example",
                    "display_name": "Example MCP",
                    "url": "https://mcp.example/rpc",
                    "transport": "streamable_http",
                    "auth_type": "bearer",
                    "auth_token": secret,
                },
            ),
            client.put(
                "/api/ops/mcp-servers/42",
                json={
                    "server_key": "example",
                    "display_name": "Example MCP",
                    "url": "https://mcp.example/rpc",
                    "transport": "streamable_http",
                    "auth_type": "bearer",
                    "auth_token": None,
                    "clear_auth_token": False,
                },
            ),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(secret, response.text)
            self.assertNotIn("auth_token\"", response.text)
        self.assertEqual(responses[0].json()["items"][0]["auth_token_masked"], "inte****oken")

    def test_update_delete_and_test_missing_rows_preserve_404_contract(self) -> None:
        repository = MagicMock(spec=McpServerConfigRepository)
        repository.update_mcp_server_config.return_value = None
        repository.delete_mcp_server_config.return_value = False
        repository.get_mcp_server_config.return_value = None
        client = self._client(repository)
        payload = {
            "server_key": "example",
            "display_name": "Example MCP",
            "url": "https://mcp.example/rpc",
        }

        self.assertEqual(client.put("/api/ops/mcp-servers/42", json=payload).status_code, 404)
        self.assertEqual(client.delete("/api/ops/mcp-servers/42").status_code, 404)
        self.assertEqual(client.post("/api/ops/mcp-servers/42/test").status_code, 404)

    def test_connection_failure_is_persisted_and_returned_as_http_200(self) -> None:
        repository = MagicMock(spec=McpServerConfigRepository)
        internal = _row(auth_token="top-secret-token")
        repository.get_mcp_server_config.return_value = internal
        repository.update_mcp_server_test_result.return_value = _row(
            auth_token="top-secret-token",
            last_test_status="failed",
            last_test_message="timeout",
        )
        result = {"status": "failed", "message": "timeout", "tools": []}

        with patch(
            "backend.app.services.mcp_connection_tester.test_mcp_server_connection",
            return_value=result,
        ) as connection_test:
            response = self._client(repository).post("/api/ops/mcp-servers/42/test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "failed")
        self.assertNotIn("top-secret-token", response.text)
        connection_test.assert_called_once_with(internal)
        repository.update_mcp_server_test_result.assert_called_once_with(42, result)

    def test_each_mcp_route_requires_admin_before_repository_calls(self) -> None:
        repository = MagicMock(spec=McpServerConfigRepository)
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        app.dependency_overrides[get_mcp_server_config_repository] = lambda: repository
        client = TestClient(app)
        payload = {
            "server_key": "example",
            "display_name": "Example MCP",
            "url": "https://mcp.example/rpc",
        }

        requests = (
            client.get("/api/ops/mcp-servers"),
            client.post("/api/ops/mcp-servers", json=payload),
            client.put("/api/ops/mcp-servers/42", json=payload),
            client.delete("/api/ops/mcp-servers/42"),
            client.post("/api/ops/mcp-servers/42/test"),
        )
        self.assertTrue(all(response.status_code in (401, 403) for response in requests))
        for method in (
            repository.list_mcp_server_configs,
            repository.create_mcp_server_config,
            repository.update_mcp_server_config,
            repository.delete_mcp_server_config,
            repository.get_mcp_server_config,
        ):
            method.assert_not_called()


class McpWireProtocolContracts(unittest.TestCase):
    def test_exact_json_rpc_sequence_timeout_and_no_remote_execution(self) -> None:
        requests: list[httpx.Request] = []
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            payload = json.loads(request.content)
            if payload["method"] == "initialize":
                self.assertEqual(
                    payload,
                    {
                        "jsonrpc": "2.0",
                        "method": "initialize",
                        "id": 1,
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {"name": "aigc-news-admin", "version": "1.0.0"},
                        },
                    },
                )
                return httpx.Response(
                    200,
                    headers={"Mcp-Session-Id": "session-1"},
                    json={"jsonrpc": "2.0", "id": "1", "result": {"protocolVersion": "2025-06-18"}},
                )
            if payload["method"] == "notifications/initialized":
                self.assertNotIn("id", payload)
                return httpx.Response(204)
            self.assertEqual(payload, {"jsonrpc": "2.0", "method": "tools/list", "id": 2, "params": {}})
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b'data: {"jsonrpc":"2.0","id":"2","result":{"tools":[]}}\n\n',
            )

        def client_factory(**kwargs):
            captured.update(kwargs)
            return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

        result = tester.test_mcp_server_connection(
            {
                "url": "https://mcp.example:8443/rpc",
                "transport": "streamable_http",
                "auth_type": "bearer",
                "auth_token": "top-secret-token",
            },
            resolver=_resolver,
            client_factory=client_factory,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(
            [json.loads(request.content)["method"] for request in requests],
            ["initialize", "notifications/initialized", "tools/list"],
        )
        self.assertNotIn("tools/call", [json.loads(request.content)["method"] for request in requests])
        self.assertFalse(captured["follow_redirects"])
        self.assertFalse(captured["trust_env"])
        self.assertEqual(captured["timeout"].connect, 5.0)
        self.assertEqual(captured["timeout"].read, 10.0)
        self.assertEqual(captured["timeout"].write, 5.0)
        self.assertEqual(captured["timeout"].pool, 5.0)

    def test_mixed_dns_response_size_and_token_redaction_fail_closed(self) -> None:
        mixed = tester.test_mcp_server_connection(
            {"url": "https://mcp.example/rpc"},
            resolver=lambda _host: [PUBLIC_IP, "10.0.0.1"],
        )
        self.assertEqual(mixed["status"], "failed")
        self.assertIn("不允许访问", mixed["message"])

        secret = "never-leak-this-token"

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"transport exposed {secret}", request=request)

        result = tester.test_mcp_server_connection(
            {
                "url": "https://mcp.example/rpc",
                "transport": "streamable_http",
                "auth_type": "bearer",
                "auth_token": secret,
            },
            resolver=_resolver,
            client_factory=lambda **kwargs: httpx.Client(
                transport=httpx.MockTransport(handler), **kwargs
            ),
        )
        self.assertEqual(result["status"], "failed")
        self.assertNotIn(secret, result["message"])


if __name__ == "__main__":
    unittest.main()
