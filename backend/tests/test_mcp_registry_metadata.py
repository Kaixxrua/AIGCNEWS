from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from backend.app.services.mcp.inbound.catalog import MCP_SERVER_NAME, MCP_SERVER_VERSION

ROOT = Path(__file__).resolve().parents[2]
SERVER_JSON = ROOT / "server.json"

# Constraints mirrored from the official MCP registry schema
# https://static.modelcontextprotocol.io/schemas/2025-10-17/server.schema.json
_NAME_RE = re.compile(r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$")
_DESCRIPTION_MAX = 100
_TITLE_MAX = 100
_ICON_MIME_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/svg+xml", "image/webp"}
_REGISTRY_NAME = "io.github.kaixxrua/aigc-radar"
_PRODUCTION_MCP_URL = "https://aigcradar.online/api/mcp"


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
        self.assertTrue(name.endswith(f"/{MCP_SERVER_NAME}"))

    def test_title_fits_schema_limit(self) -> None:
        title = self.document["title"]
        self.assertGreaterEqual(len(title), 1)
        self.assertLessEqual(len(title), _TITLE_MAX)

    def test_description_fits_schema_limit(self) -> None:
        description = self.document["description"]
        self.assertGreaterEqual(len(description), 1)
        self.assertLessEqual(len(description), _DESCRIPTION_MAX)

    def test_version_matches_server_info(self) -> None:
        self.assertEqual(self.document["version"], MCP_SERVER_VERSION)

    def test_hosted_remote_points_to_production_endpoint(self) -> None:
        remotes = self.document["remotes"]
        self.assertEqual(len(remotes), 1)
        remote = remotes[0]
        self.assertEqual(remote["type"], "streamable-http")
        self.assertEqual(remote["url"], _PRODUCTION_MCP_URL)
        self.assertNotIn("packages", self.document)

    def test_repository_and_website_are_public_urls(self) -> None:
        repository = self.document["repository"]
        self.assertEqual(repository["source"], "github")
        self.assertTrue(repository["url"].startswith("https://"), repository["url"])
        self.assertTrue(self.document["websiteUrl"].startswith("https://"))

    def test_icons_use_allowed_mime_types(self) -> None:
        for icon in self.document.get("icons", []):
            self.assertTrue(icon["src"].startswith("https://"), icon["src"])
            if "mimeType" in icon:
                self.assertIn(icon["mimeType"], _ICON_MIME_TYPES)


if __name__ == "__main__":
    unittest.main()
