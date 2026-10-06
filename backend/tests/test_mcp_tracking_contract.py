"""get_my_tracking 的跨语言契约（工具在 mcp-go，scope 签发与追踪数据在 Python）。

Go 与 Python 各自写死同一组字面量：token scope、工具名，以及追踪简报条目的
JSON 字段。这里双向钉住，任何一侧改名都会在 CI 里失败。
"""

from __future__ import annotations

import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.app.api import routes_auth
from backend.app.domain.tracking import clean_item
from backend.app.monitoring.mcp_tools import MCP_TOOL_NAMES

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MCPAPP = _REPO_ROOT / "mcp-go" / "internal" / "mcpapp"


def _read(relative: str) -> str:
    return (_REPO_ROOT / relative).read_text(encoding="utf-8")


class TrackingScopeContractTests(unittest.TestCase):
    def test_go_scope_literals_are_grantable(self) -> None:
        tracking = (_MCPAPP / "tracking.go").read_text(encoding="utf-8")
        favorites = (_MCPAPP / "favorites.go").read_text(encoding="utf-8")
        self.assertIn('const TrackingReadScope = "tracking:read"', tracking)
        self.assertIn("identity.HasScope(TrackingReadScope)", tracking)
        self.assertIn('identity.HasScope("projects:favorites:read")', favorites)
        self.assertEqual(
            routes_auth.MCP_TOKEN_SCOPES, frozenset({"projects:favorites:read", "tracking:read"})
        )

    def test_default_and_dsh_tokens_carry_both_read_scopes(self) -> None:
        self.assertEqual(routes_auth.DEFAULT_MCP_TOKEN_SCOPES, ("projects:favorites:read", "tracking:read"))
        self.assertEqual(
            routes_auth.CreateMcpTokenRequest(client_type="claude").scopes,
            ["projects:favorites:read", "tracking:read"],
        )
        self.assertEqual(routes_auth._DSH_MCP_TOKEN_SCOPES, ["projects:favorites:read", "tracking:read"])
        self.assertTrue(set(routes_auth.DEFAULT_MCP_TOKEN_SCOPES) <= routes_auth.MCP_TOKEN_SCOPES)


class TrackingToolNameContractTests(unittest.TestCase):
    def test_tool_is_listed_registered_and_counted_under_one_name(self) -> None:
        catalog = (_MCPAPP / "catalog_tools.go").read_text(encoding="utf-8")
        main = _read("mcp-go/cmd/mcp-server/main.go")
        private = catalog[catalog.index("var privateTools = []any{") :]
        names = re.findall(r'\{Key: "name", Value: "([a-z_]+)"\}', private)
        self.assertEqual(names, ["search_my_project_favorites", "get_my_tracking"])
        self.assertIn('app.RegisterIdentityTool("get_my_tracking", tracking.Get)', main)
        self.assertIn('knownToolNames["get_my_tracking"] = struct{}{}', main)
        # Python 计数名单按 Go catalog 顺序同步：私有工具追加在末尾
        self.assertEqual(MCP_TOOL_NAMES[-2:], ("search_my_project_favorites", "get_my_tracking"))


class TrackingItemShapeContractTests(unittest.TestCase):
    def test_go_decoder_reads_fields_written_by_clean_item(self) -> None:
        source = _read("mcp-go/internal/postgres/tracking.go")
        struct = re.search(r"type trackingItemJSON struct \{(.*?)\n\}", source, re.S)
        assert struct is not None
        go_fields = set(re.findall(r'json:"([a-z_]+)"', struct.group(1)))
        item = clean_item(
            {
                "observed_at": datetime(2026, 10, 5, 22, 0, tzinfo=timezone.utc),
                "key": "news:1",
                "title": "Agent SDK 1.0",
                "url": "https://example.com/a",
                "summary": "summary",
                "source": "news",
            },
            "Agent",
        )
        assert item is not None
        self.assertEqual(go_fields, {"observed_at", "title", "url", "summary", "source", "matched_rules"})
        self.assertTrue(go_fields <= set(item), f"{sorted(go_fields - set(item))} 不在 clean_item 输出里")
        self.assertEqual(item["matched_rules"], ["Agent"])
        # Go 侧只收 https 链接；clean_item 也只放行 https 公网链接
        self.assertIsNone(clean_item({**{"key": "k", "source": "news"}, "url": "http://example.com/a"}, "Agent"))
        self.assertIn('strings.HasPrefix(item.URL, "https://")', source)


if __name__ == "__main__":
    unittest.main()
