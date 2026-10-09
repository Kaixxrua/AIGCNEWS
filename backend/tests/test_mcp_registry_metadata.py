from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_JSON = ROOT / "server.json"
# 入站 MCP 栈退役后，serverInfo 名称/版本由 Go 网关持有
# （mcp-go/internal/version/version.go：运行时优先读 server.json，常量兜底）。
# 此处钉住 server.json 与 Go 兜底常量同值，防止双语漂移。
GO_VERSION_SOURCE = ROOT / "mcp-go" / "internal" / "version" / "version.go"

# Constraints mirrored from the official MCP registry schema
# https://static.modelcontextprotocol.io/schemas/2025-10-17/server.schema.json
_NAME_RE = re.compile(r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$")
_DESCRIPTION_MAX = 100
_TITLE_MAX = 100
_ICON_MIME_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/svg+xml", "image/webp"}
# registry 命名空间区分大小写，必须与 GitHub 登录名一致（大写 K），小写会被 publish 以 403 拒绝。
_REGISTRY_NAME = "io.github.Kaixxrua/aigc-radar"
_PRODUCTION_MCP_URL = "https://aigcnews.cn/api/mcp"


def _go_version_const(name: str) -> str:
    match = re.search(
        rf'\b{name} = "([^"]+)"',
        GO_VERSION_SOURCE.read_text(encoding="utf-8"),
    )
    assert match, f"{name} not found in {GO_VERSION_SOURCE}"
    return match.group(1)


class RegistryMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads(SERVER_JSON.read_text(encoding="utf-8"))

    def test_schema_url_is_official_registry_schema(self) -> None:
        schema_url = self.document["$schema"]
        self.assertTrue(
            schema_url.startswith("https://static.modelcontextprotocol.io/schemas/"),
            schema_url,
        )
        self.assertTrue(schema_url.endswith("/server.schema.json"), schema_url)

    def test_name_matches_registry_pattern_and_brand(self) -> None:
        name = self.document["name"]
        self.assertEqual(name, _REGISTRY_NAME)
        self.assertRegex(name, _NAME_RE)
        self.assertGreaterEqual(len(name), 3)
        self.assertLessEqual(len(name), 200)
        self.assertTrue(name.endswith(f"/{_go_version_const('ServerName')}"))

    def test_title_fits_schema_limit(self) -> None:
        title = self.document["title"]
        self.assertGreaterEqual(len(title), 1)
        self.assertLessEqual(len(title), _TITLE_MAX)

    def test_description_fits_schema_limit(self) -> None:
        description = self.document["description"]
        self.assertGreaterEqual(len(description), 1)
        self.assertLessEqual(len(description), _DESCRIPTION_MAX)

    def test_version_matches_go_server_info_fallback(self) -> None:
        self.assertEqual(self.document["version"], _go_version_const("Fallback"))

    def test_hosted_remote_points_to_production_endpoint(self) -> None:
        remotes = self.document["remotes"]
        self.assertEqual(len(remotes), 1)
        remote = remotes[0]
        self.assertEqual(remote["type"], "streamable-http")
        self.assertEqual(remote["url"], _PRODUCTION_MCP_URL)
        self.assertNotIn("packages", self.document)

    def test_website_is_public_url(self) -> None:
        self.assertTrue(self.document["websiteUrl"].startswith("https://"))

    def test_repository_omitted_while_main_repo_is_private(self) -> None:
        # 主仓库未公开：registry 与目录站会把 repository 显示成链接，指向私有仓库只会 404。
        # 仓库公开时再加回 repository，并把本测试改回校验公开 URL。
        self.assertNotIn("repository", self.document)

    def test_icons_use_allowed_mime_types(self) -> None:
        for icon in self.document.get("icons", []):
            self.assertTrue(icon["src"].startswith("https://"), icon["src"])
            if "mimeType" in icon:
                self.assertIn(icon["mimeType"], _ICON_MIME_TYPES)


if __name__ == "__main__":
    unittest.main()
