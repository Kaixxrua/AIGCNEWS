"""/api/version 端点测试：版本与 server.json / MCP serverInfo 同源。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.app.core.app_version import _FALLBACK_APP_VERSION
from backend.app.main import _APP_VERSION, _resolve_app_version, app

SERVER_JSON = Path(__file__).resolve().parents[2] / "server.json"


class ApiVersionTests(unittest.TestCase):
    def test_version_matches_server_json(self) -> None:
        document = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
        self.assertEqual(_resolve_app_version(), document["version"])

    def test_fallback_matches_server_json(self) -> None:
        # 容器内无 server.json 时回退常量必须与清单同值（入站 MCP 栈退役后
        # 不再与 services.mcp 常量联动，本断言承接防漂移职责）。
        document = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
        self.assertEqual(_FALLBACK_APP_VERSION, document["version"])

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
