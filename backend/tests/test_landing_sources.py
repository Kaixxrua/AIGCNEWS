"""429 提示链接落地来源的白名单与归一（services/dashboard/landing_sources）。

来源标记字面量是跨语言契约：Go 的 ratelimit/projection.go、Python 的
routes_projects_api.py 与前端 visitBeacon.ts 各自写死同一组值。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from backend.app.repositories.site_visit_repository import LandingVisits
from backend.app.services.dashboard.landing_sources import (
    LANDING_PATHS,
    LANDING_SOURCES,
    OTHER_LANDING_PATH,
    build_landing_rows,
    normalize_landing,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REF_PATTERN = re.compile(r"https://aigcnews\.cn(/[a-z]+)\?ref=([a-z0-9-]+)")


def _tagged_links(relative_path: str) -> set[tuple[str, str]]:
    text = (_REPO_ROOT / relative_path).read_text(encoding="utf-8")
    return {(path, ref) for path, ref in _REF_PATTERN.findall(text)}


class NormalizeLandingTests(unittest.TestCase):
    def test_known_ref_on_known_path(self) -> None:
        self.assertEqual(normalize_landing("mcp-429-anon", "/mcp"), ("mcp-429-anon", "/mcp"))
        self.assertEqual(
            normalize_landing("api-429-monthly", "/membership"),
            ("api-429-monthly", "/membership"),
        )

    def test_unknown_or_missing_ref_records_nothing(self) -> None:
        for ref in (None, "", "mcp-429", "mcp-429-anon.", "MCP-429-ANON", "utm_x", "mcp-429-anon " * 3):
            with self.subTest(ref=ref):
                self.assertIsNone(normalize_landing(ref, "/mcp"))

    def test_surrounding_whitespace_is_tolerated(self) -> None:
        self.assertEqual(normalize_landing(" mcp-429-daily ", " /membership "), ("mcp-429-daily", "/membership"))

    def test_trailing_slash_and_case_fold_to_known_path(self) -> None:
        self.assertEqual(normalize_landing("mcp-429-anon", "/mcp/"), ("mcp-429-anon", "/mcp"))
        self.assertEqual(normalize_landing("mcp-429-anon", "/Membership"), ("mcp-429-anon", "/membership"))

    def test_other_paths_collapse_to_other(self) -> None:
        for path in (None, "", "/", "/mcp/clients", "/membership/checkout", "/../etc", "x" * 256):
            with self.subTest(path=path):
                self.assertEqual(normalize_landing("api-429-anon", path), ("api-429-anon", OTHER_LANDING_PATH))


class BuildLandingRowsTests(unittest.TestCase):
    def test_sorted_by_landings_then_source_then_path(self) -> None:
        rows = build_landing_rows(
            [
                LandingVisits(source="mcp-429-daily", path="/membership", landings=2),
                LandingVisits(source="mcp-429-anon", path="/membership", landings=5),
                LandingVisits(source="mcp-429-anon", path="/mcp", landings=5),
                LandingVisits(source="api-429-anon", path="other", landings=2),
            ]
        )

        self.assertEqual(
            rows,
            [
                {"source": "mcp-429-anon", "path": "/mcp", "landings": 5},
                {"source": "mcp-429-anon", "path": "/membership", "landings": 5},
                {"source": "api-429-anon", "path": "other", "landings": 2},
                {"source": "mcp-429-daily", "path": "/membership", "landings": 2},
            ],
        )


class CrossLanguageLiteralTests(unittest.TestCase):
    """429 文案里出现的 (落地页, ref) 必须全在白名单内，且两侧各用满三种变体。"""

    def _assert_links(self, relative_path: str, prefix: str) -> None:
        links = _tagged_links(relative_path)
        self.assertEqual(
            links,
            {
                ("/mcp", f"{prefix}-429-anon"),
                ("/membership", f"{prefix}-429-anon"),
                ("/membership", f"{prefix}-429-daily"),
                ("/membership", f"{prefix}-429-monthly"),
            },
        )
        for path, ref in links:
            self.assertIn(ref, LANDING_SOURCES)
            self.assertIn(path, LANDING_PATHS)

    def test_go_mcp_projection_links(self) -> None:
        self._assert_links("mcp-go/internal/ratelimit/projection.go", "mcp")

    def test_python_rest_projection_links(self) -> None:
        self._assert_links("backend/app/api/routes_projects_api.py", "api")

    def test_frontend_beacon_allow_list_matches(self) -> None:
        text = (_REPO_ROOT / "frontend/src/services/visit/visitBeacon.ts").read_text(encoding="utf-8")
        # 前端只认这组前缀，后面跟着标点或中文（聊天里粘贴链接常见）也取规范标记上报
        self.assertIn(
            r"const landingRefPattern = /^(?:mcp|api)-429-(?:anon|daily|monthly)(?![\w-])/",
            text,
            "visitBeacon.ts 的 ref 白名单与后端 LANDING_SOURCES 脱钩",
        )
        self.assertEqual(
            set(LANDING_SOURCES),
            {f"{side}-429-{kind}" for side in ("mcp", "api") for kind in ("anon", "daily", "monthly")},
        )


if __name__ == "__main__":
    unittest.main()
