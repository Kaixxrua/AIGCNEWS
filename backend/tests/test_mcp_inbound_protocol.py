from __future__ import annotations

import json
import types
import unittest
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
from backend.app.services.mcp.inbound import application, catalog, context, tools

PUBLIC_TOOL_NAMES = [
    "search_papers",
    "search_documents",
    "get_paper_detail",
    "get_top_items",
    "search_github_projects",
    "search_github_ai_projects",
    "get_project_library",
    "get_project_categories",
]
PRIVATE_TOOL_NAME = "search_my_project_favorites"
RESOURCE_URIS = [
    "aigc-news://dashboard/summary",
    "aigc-news://projects/categories",
    "aigc-news://report/latest",
]
RESOURCE_TEMPLATES = [
    "aigc-news://dashboard/top{?source,period,date,limit}",
    "aigc-news://papers/{paper_id}",
    "aigc-news://projects/library{?q,category,subcategory,language,scope,sort,page,limit}",
    "aigc-news://report/latest{?source,period,date}",
]
PROMPT_NAMES = ["daily_research_brief", "project_discovery"]


class McpInboundProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        self.briefing_repository = MagicMock()
        self.token_repository = MagicMock()
        self.project_collections = MagicMock()
        self.project_search_runtime = MagicMock()
        self.project_search_runtime.search_projects = AsyncMock()
        self.repositories = types.SimpleNamespace(
            documents=MagicMock(),
            rank_snapshots=MagicMock(),
            project_collections=self.project_collections,
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

    def rpc(self, method: str, *, request_id=1, params=None, headers=None):
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        return self.client.post("/api/mcp", json=payload, headers=headers)

    def assert_rpc_error(self, response, *, code: int, message: str, request_id=None):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": message},
            },
        )
        self.assertEqual(
            response.headers["mcp-protocol-version"],
            catalog.MCP_PROTOCOL_VERSION,
        )

    def test_parse_and_body_limits(self) -> None:
        for body in (b"", b"{", b"\xff"):
            with self.subTest(body=body):
                self.assert_rpc_error(
                    self.client.post(
                        "/api/mcp",
                        content=body,
                        headers={"content-type": "application/json"},
                    ),
                    code=-32700,
                    message="Parse error",
                )

        oversized = b" " * (catalog.MAX_REQUEST_BYTES + 1)
        self.assert_rpc_error(
            self.client.post(
                "/api/mcp",
                content=oversized,
                headers={"content-type": "application/json"},
            ),
            code=-32600,
            message="Request body too large",
        )

    def test_batch_and_scalar_requests_are_rejected(self) -> None:
        for payload in ([], [{}]):
            with self.subTest(payload=payload):
                self.assert_rpc_error(
                    self.client.post("/api/mcp", json=payload),
                    code=-32600,
                    message="Batch JSON-RPC requests are not supported",
                )
        for payload in (None, True, 1, 1.5, "request"):
            with self.subTest(payload=payload):
                self.assert_rpc_error(
                    self.client.post("/api/mcp", content=json.dumps(payload)),
                    code=-32600,
                    message="Invalid Request",
                )

    def test_version_method_params_and_required_id_validation(self) -> None:
        cases = [
            ({"id": 7, "method": "tools/list"}, -32600, "Invalid JSON-RPC version", 7),
            ({"jsonrpc": "1.0", "id": 7, "method": "tools/list"}, -32600, "Invalid JSON-RPC version", 7),
            ({"jsonrpc": "2.0", "id": 7}, -32600, "Missing method", 7),
            ({"jsonrpc": "2.0", "id": 7, "method": False}, -32600, "Missing method", 7),
            ({"jsonrpc": "2.0", "method": "tools/list"}, -32600, "Request id is required", None),
            ({"jsonrpc": "2.0", "id": {}, "method": "tools/list"}, -32600, "Invalid request id", None),
        ]
        for payload, code, message, request_id in cases:
            with self.subTest(payload=payload):
                self.assert_rpc_error(
                    self.client.post("/api/mcp", json=payload),
                    code=code,
                    message=message,
                    request_id=request_id,
                )

        for params in (None, False, "", 0, []):
            with self.subTest(params=params):
                self.assert_rpc_error(
                    self.client.post(
                        "/api/mcp",
                        json={
                            "jsonrpc": "2.0",
                            "id": 8,
                            "method": "tools/list",
                            "params": params,
                        },
                    ),
                    code=-32602,
                    message="params must be an object",
                    request_id=8,
                )

    def test_explicit_null_float_and_boolean_ids_are_reflected(self) -> None:
        for request_id in (None, 1.25, True, False):
            with self.subTest(request_id=request_id):
                response = self.rpc("tools/list", request_id=request_id)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["id"], request_id)

    def test_notification_is_204_but_other_idless_calls_are_errors(self) -> None:
        notification = self.client.post(
            "/api/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        )
        self.assertEqual(notification.status_code, 204)
        self.assertEqual(notification.content, b"")
        self.assertEqual(
            notification.headers["mcp-protocol-version"],
            catalog.MCP_PROTOCOL_VERSION,
        )
        self.assert_rpc_error(
            self.client.post(
                "/api/mcp",
                json={"jsonrpc": "2.0", "method": "notifications/other"},
            ),
            code=-32600,
            message="Request id is required",
        )

    def test_initialize_exact_shape_headers_and_stateless_followup(self) -> None:
        response = self.rpc("initialize", request_id="init", params={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "jsonrpc": "2.0",
                "id": "init",
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                        "prompts": {"listChanged": False},
                    },
                    "serverInfo": {"name": "aigc-news", "version": "1.1.0"},
                    "instructions": catalog.MCP_HOST_INSTRUCTIONS,
                },
            },
        )
        session_id = response.headers["mcp-session-id"]
        self.assertRegex(session_id, r"^aigc-news-[0-9a-f]{32}$")
        self.assertEqual(response.headers["mcp-protocol-version"], "2025-06-18")

        without_session = self.rpc("tools/list", request_id=2)
        with_unknown_session = self.rpc(
            "tools/list",
            request_id=3,
            headers={"Mcp-Session-Id": "not-the-initialize-session"},
        )
        self.assertEqual(without_session.status_code, 200)
        self.assertEqual(with_unknown_session.status_code, 200)
        self.assertNotIn("mcp-session-id", without_session.headers)
        self.assertNotIn("mcp-session-id", with_unknown_session.headers)

    def test_session_transport_seam_controls_initialize_only(self) -> None:
        transport = MagicMock(spec=context.McpSessionTransport)
        transport.new_session_id.return_value = "aigc-news-fixed-session"
        transport.headers.side_effect = context.McpSessionTransport().headers

        with patch.object(routes_mcp, "_MCP_SESSION_TRANSPORT", transport):
            initialized = self.rpc("initialize", request_id="init")
            listed = self.rpc(
                "tools/list",
                request_id=2,
                headers={"Mcp-Session-Id": "ignored-client-session"},
            )

        self.assertEqual(
            initialized.headers["mcp-session-id"], "aigc-news-fixed-session"
        )
        self.assertNotIn("mcp-session-id", listed.headers)
        transport.new_session_id.assert_called_once_with()
        transport.headers.assert_any_call("aigc-news-fixed-session")

    def test_unknown_method_uses_jsonrpc_method_not_found(self) -> None:
        self.assert_rpc_error(
            self.rpc("unknown/method", request_id="unknown", params={}),
            code=-32601,
            message="Method not found",
            request_id="unknown",
        )

    def test_route_composes_immutable_context_and_delegates_dispatch(self) -> None:
        projection = application.McpProtocolResponse(
            status_code=200,
            body={"jsonrpc": "2.0", "id": 11, "result": {"tools": []}},
            headers={"MCP-Protocol-Version": "2025-06-18"},
        )
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=projection)

        with patch.object(
            routes_mcp,
            "McpProtocolApplication",
            return_value=dispatcher,
        ) as application_factory:
            response = self.rpc("tools/list", request_id=11)

        self.assertEqual(response.json(), projection.body)
        dispatcher.dispatch.assert_awaited_once()
        inbound = dispatcher.dispatch.await_args.args[0]
        self.assertEqual(inbound.method, "tools/list")
        dependencies = application_factory.call_args.args[0]
        self.assertIsInstance(dependencies, application.McpProtocolDependencies)
        self.assertIs(dependencies.tools.documents, self.repositories.documents)
        self.assertIs(
            dependencies.tools.project_collection,
            self.repositories.project_collections,
        )
        self.assertIs(dependencies.briefing_repository, self.briefing_repository)
        self.assertIs(dependencies.session_transport, routes_mcp._MCP_SESSION_TRANSPORT)

    def test_protocol_dependencies_and_response_are_immutable(self) -> None:
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
        )
        response = application.McpProtocolResponse(204, None, {})

        with self.assertRaises(AttributeError):
            dependencies.briefing_repository = MagicMock()
        with self.assertRaises(AttributeError):
            response.status_code = 200

    def test_canonical_registry_pairs_catalog_models_and_handlers(self) -> None:
        expected_names = [*PUBLIC_TOOL_NAMES, PRIVATE_TOOL_NAME]
        self.assertEqual(list(tools.MCP_TOOL_REGISTRY), expected_names)
        self.assertEqual(set(catalog.MCP_TOOL_DEFINITIONS), set(expected_names))
        self.assertEqual(set(catalog.MCP_TOOL_INPUT_MODELS), set(expected_names))
        for name, registration in tools.MCP_TOOL_REGISTRY.items():
            with self.subTest(name=name):
                self.assertIs(
                    registration["definition"], catalog.MCP_TOOL_DEFINITIONS[name]
                )
                self.assertIs(
                    registration["input_model"], catalog.MCP_TOOL_INPUT_MODELS[name]
                )
                self.assertIs(registration["handler"], tools._TOOL_HANDLERS[name])
                self.assertEqual(
                    registration["definition"]["inputSchema"],
                    registration["input_model"].model_json_schema(),
                )

    def test_public_resources_templates_and_prompts_inventory_order(self) -> None:
        tools = self.rpc("tools/list").json()["result"]["tools"]
        resources = self.rpc("resources/list").json()["result"]["resources"]
        templates = self.rpc("resources/templates/list").json()["result"][
            "resourceTemplates"
        ]
        prompts = self.rpc("prompts/list").json()["result"]["prompts"]

        self.assertEqual([item["name"] for item in tools], PUBLIC_TOOL_NAMES)
        self.assertEqual([item["uri"] for item in resources], RESOURCE_URIS)
        self.assertEqual(
            [item["uriTemplate"] for item in templates], RESOURCE_TEMPLATES
        )
        self.assertEqual([item["name"] for item in prompts], PROMPT_NAMES)

    def test_authenticated_inventory_and_owner_scoped_private_execution(self) -> None:
        self.token_repository.get_user_by_mcp_token_hash.side_effect = lambda _digest: {
            "user_id": 42,
            "scopes": ["projects:favorites:read"],
        }
        self.project_collections.list_user_project_collection.return_value = {
            "items": [],
            "total": 0,
        }
        headers = {"Authorization": "Bearer valid-token"}

        tools = self.rpc("tools/list", headers=headers).json()["result"]["tools"]
        self.assertEqual(
            [item["name"] for item in tools],
            [*PUBLIC_TOOL_NAMES, PRIVATE_TOOL_NAME],
        )
        result = self.rpc(
            "tools/call",
            request_id=2,
            params={"name": PRIVATE_TOOL_NAME, "arguments": {"q": "agent"}},
            headers=headers,
        ).json()["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(
            self.project_collections.list_user_project_collection.call_args.kwargs[
                "user_id"
            ],
            42,
        )

    def test_private_visibility_is_separate_from_scope_execution(self) -> None:
        anonymous = self.rpc(
            "tools/call",
            params={"name": PRIVATE_TOOL_NAME, "arguments": {}},
        ).json()["result"]
        self.assertTrue(anonymous["isError"])
        self.assertIn("Authentication", anonymous["content"][0]["text"])

        self.token_repository.get_user_by_mcp_token_hash.side_effect = lambda _digest: {
            "user_id": 42,
            "scopes": [],
        }
        headers = {"Authorization": "Bearer limited-token"}
        listed_names = [
            item["name"]
            for item in self.rpc("tools/list", headers=headers).json()["result"][
                "tools"
            ]
        ]
        self.assertIn(PRIVATE_TOOL_NAME, listed_names)
        denied = self.rpc(
            "tools/call",
            params={"name": PRIVATE_TOOL_NAME, "arguments": {}},
            headers=headers,
        ).json()["result"]
        self.assertTrue(denied["isError"])
        self.assertIn("projects:favorites:read", denied["content"][0]["text"])
        self.project_collections.list_user_project_collection.assert_not_called()

    def test_tool_errors_stay_in_result_while_rpc_errors_use_error_envelope(self) -> None:
        unknown_tool = self.rpc(
            "tools/call",
            request_id=5,
            params={"name": "not-a-tool", "arguments": {}},
        ).json()
        self.assertNotIn("error", unknown_tool)
        self.assertEqual(unknown_tool["id"], 5)
        self.assertTrue(unknown_tool["result"]["isError"])
        self.assertNotIn("structuredContent", unknown_tool["result"])

        missing_name = self.rpc(
            "tools/call", request_id=6, params={"arguments": {}}
        )
        self.assert_rpc_error(
            missing_name,
            code=-32602,
            message="tools/call params.name is required",
            request_id=6,
        )

        handler = AsyncMock(side_effect=RuntimeError("private implementation detail"))
        with patch.dict(tools._TOOL_HANDLERS, {"search_papers": handler}):
            failed = self.rpc(
                "tools/call",
                request_id=7,
                params={"name": "search_papers", "arguments": {"q": "agent"}},
            ).json()["result"]
        self.assertTrue(failed["isError"])
        self.assertIn("Tool execution failed.", failed["content"][0]["text"])
        self.assertNotIn("private implementation detail", failed["content"][0]["text"])

    def test_tool_and_resource_results_are_truncated(self) -> None:
        oversized = "x" * (catalog.MAX_TOOL_RESULT_CHARS + 1)
        handler = AsyncMock(return_value={"value": oversized})
        with patch.dict(tools._TOOL_HANDLERS, {"search_papers": handler}):
            tool_result = self.rpc(
                "tools/call",
                params={"name": "search_papers", "arguments": {"q": "agent"}},
            ).json()["result"]
        self.assertFalse(tool_result["isError"])
        self.assertTrue(tool_result["structuredContent"]["truncated"])
        self.assertEqual(
            len(tool_result["structuredContent"]["preview"]),
            catalog.MAX_TOOL_RESULT_CHARS,
        )
        self.assertEqual(
            json.loads(tool_result["content"][0]["text"]),
            tool_result["structuredContent"],
        )

        self.briefing_repository.get_briefing_by_date.return_value = {
            "content": "y" * (catalog.MAX_RESOURCE_TEXT_CHARS + 1)
        }
        resource = self.rpc(
            "resources/read",
            params={"uri": "aigc-news://report/latest"},
        ).json()["result"]["contents"][0]
        self.assertEqual(
            resource["text"],
            "y" * catalog.MAX_RESOURCE_TEXT_CHARS + "\n\n[truncated]",
        )

    def test_invalid_authorization_header_is_http_401_not_jsonrpc(self) -> None:
        response = self.rpc(
            "tools/list",
            headers={"Authorization": "Basic invalid"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")
        self.assertEqual(
            response.json(), {"detail": "Authorization 必须使用 Bearer Token"}
        )
        self.assertNotIn("jsonrpc", response.json())


if __name__ == "__main__":
    unittest.main()
