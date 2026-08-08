"""/api/version 端点测试：版本与 server.json / MCP serverInfo 同源。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.app.main import _APP_VERSION, _resolve_app_version, app
from backend.app.services.mcp.inbound.catalog import MCP_SERVER_VERSION

SERVER_JSON = Path(__file__).resolve().parents[2] / "server.json"


class ApiVersionTests(unittest.TestCase):
    def test_version_matches_server_json(self) -> None:
        document = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
        self.assertEqual(_resolve_app_version(), document["version"])

    def test_version_matches_mcp_server_info(self) -> None:
        self.assertEqual(_resolve_app_version(), MCP_SERVER_VERSION)

    def test_not_hardcoded_legacy_default(self) -> None:
        self.assertNotEqual(_APP_VERSION, "1.0.0")

    def test_route_registered(self) -> None:
        routes = {
            getattr(route, "path", None)
            for route in app.routes
            if "GET" in getattr(route, "methods", set())
        }
        self.assertIn("/api/version", routes)


if __name__ == "__main__":
    unittest.main()
