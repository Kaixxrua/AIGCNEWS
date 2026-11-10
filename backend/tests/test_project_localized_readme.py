"""Bounded identity evidence from a translation explicitly linked by the README."""

from __future__ import annotations

import base64
import unittest
from unittest.mock import patch

import httpx

from backend.app.services.project_catalog import descriptions_service as service
from backend.app.services.project_catalog.game_details import normalize_game_details

REPO = "acme/game"


def document(path: str, text: str, **changes: object) -> httpx.Response:
    return httpx.Response(200, json={
        "path": path, "type": "file", "encoding": "base64",
        "content": base64.b64encode(text.encode()).decode(), **changes,
    })


class LocalizedReadmeTests(unittest.IsolatedAsyncioTestCase):
    async def fetch(
        self, primary: str, localized: httpx.Response | None = None, *,
        readme_path: str = "README.md", branch: str = "main", game_details: bool = True,
    ) -> tuple[dict, list[httpx.Request]]:
        seen = []

        def handle(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.host, "api.github.com")
            self.assertEqual(request.url.scheme, "https")
            self.assertEqual(request.headers.get("Authorization"), "Bearer test-github-token")
            if request.url.path == f"/repos/{REPO}":
                return httpx.Response(200, json={
                    "full_name": REPO, "private": False, "visibility": "public",
                    "description": "A public project", "default_branch": branch,
                })
            if request.url.path == f"/repos/{REPO}/readme":
                return document(readme_path, primary)
            self.assertTrue(request.url.path.startswith(f"/repos/{REPO}/contents/"))
            self.assertEqual(request.url.params.get("ref"), branch)
            return localized if localized is not None else httpx.Response(404)

        with patch.object(service, "_build_headers", return_value={"Authorization": "Bearer test-github-token"}):
            result = await service.fetch_public_repository(REPO, game_details=game_details, transport=httpx.MockTransport(handle))
        return result, seen

    async def test_linked_translation_supplies_real_game_identity_without_inventing_it(self):
        primary = "# Project\n\n[简体中文](./README-zh_CN.md)\n\n## Environment\nUse pnpm."
        localized = "# 星海矿工\n\n这是一款探索星空的采矿游戏。"
        result, seen = await self.fetch(primary, document("README-zh_CN.md", localized))
        self.assertEqual(len(seen), 3)
        self.assertEqual(str(seen[2].url), f"https://api.github.com/repos/{REPO}/contents/README-zh_CN.md?ref=main")
        self.assertEqual(result["readme_path"], "README.md")
        self.assertEqual(result["readme_localized_path"], "README-zh_CN.md")
        self.assertTrue(result["readme_text"].startswith(primary))
        self.assertIn(localized, result["readme_text"])
        details = normalize_game_details({
            "game_identity": "single_game", "game_name_original": "星海矿工", "game_name_zh": "星海矿工",
        }, result)
        self.assertEqual(details["gameNameOriginal"], "星海矿工")
        self.assertEqual(details["gameNameZh"], "星海矿工")

    async def test_relative_and_same_repository_html_links_use_current_branch(self):
        cases = [
            (".github/README.md", "[中文](../README.zh-CN.md)", "README.zh-CN.md"),
            ("README.md", '<a href="https://github.com/Acme/Game/blob/release/stable/docs/zh/README.md">中文</a>', "docs/zh/README.md"),
        ]
        for primary_path, link, localized_path in cases:
            with self.subTest(link=link):
                result, seen = await self.fetch(link, document(localized_path, "# 游戏名称"), readme_path=primary_path, branch="release/stable")
                self.assertEqual(len(seen), 3)
                self.assertEqual(seen[2].url.path, f"/repos/{REPO}/contents/{localized_path}")
                self.assertEqual(seen[2].url.params.get("ref"), "release/stable")
                self.assertEqual(result["readme_localized_path"], localized_path)

    async def test_follows_at_most_one_link_and_never_recurses(self):
        primary = "[English](README.en.md) [中文](README.zh.md) [日本語](README.ja.md)"
        translated = "# 星海矿工\n[More](README.ja.md)"
        result, seen = await self.fetch(primary, document("README.zh.md", translated))
        self.assertEqual(len(seen), 3)
        self.assertEqual(seen[-1].url.path, f"/repos/{REPO}/contents/README.zh.md")
        self.assertIn(translated, result["readme_text"])

    async def test_sufficient_primary_readme_or_legacy_profile_never_adds_request(self):
        for primary in [
            "# Project\nA game about exploring space. [中文](README.zh.md)",
            "# 项目\n这是一款太空游戏。[中文](README.zh.md)",
            "Detailed project prose. " * 100 + "[中文](README.zh.md)",
        ]:
            with self.subTest(primary=primary[:50]):
                result, seen = await self.fetch(primary)
                self.assertEqual(len(seen), 2)
                self.assertNotIn("readme_localized_path", result)
                self.assertEqual(result["readme_text"], primary)
        result, seen = await self.fetch("[中文](README.zh.md)", game_details=False)
        self.assertEqual(len(seen), 1)
        self.assertNotIn("readme_localized_path", result)

    async def test_unlinked_hidden_non_readme_or_unsafe_targets_never_receive_requests(self):
        for primary in [
            "README.zh.md", "[Guide](CONTRIBUTING.md)", "[中文](README.zh.md?token=secret)",
            "[中文](README.zh.md#section)", "[中文](../README.zh.md)",
            "[中文](%2e%2e/README.zh.md)", "[中文](%252e%252e/README.zh.md)",
            "[中文](docs/../../README.zh.md)", r"[中文](docs\README.zh.md)",
            "[中文](https://evil.example/README.zh.md)", "[中文](//evil.example/README.zh.md)",
            "[中文](http://127.0.0.1/README.zh.md)", "[中文](file:///README.zh.md)",
            "[中文](https://github.com/other/repo/blob/main/README.zh.md)",
            "[中文](https://github.com/acme/game/blob/other/README.zh.md)",
            "[中文](https://secret@github.com/acme/game/blob/main/README.zh.md)",
            "[中文](https://github.com:443/acme/game/blob/main/README.zh.md)",
            "[中文](https://github.com/acme/game/blob/main/../README.zh.md)",
            "<!-- [中文](README.zh.md) -->", "```md\n[中文](README.zh.md)\n```",
            "`[中文](README.zh.md)`", "![中文](README.zh.md)",
            '<img src="README.zh.md">', "[Self](./README.md)",
        ]:
            with self.subTest(primary=primary):
                result, seen = await self.fetch(primary)
                self.assertEqual(len(seen), 2)
                self.assertNotIn("readme_localized_path", result)
                self.assertEqual(result["readme_text"], primary)

    async def test_optional_missing_invalid_or_redirected_translation_preserves_primary(self):
        primary = "# Project\n[中文](README.zh.md) [Other](README.ja.md)"
        for response in [
            httpx.Response(404), httpx.Response(503),
            httpx.Response(302, headers={"Location": "https://evil.example/README.zh.md"}),
            httpx.Response(200, text="invalid JSON"),
            document("README.zh.md", "", encoding="none", download_url="https://evil.example/README.zh.md"),
            document("README.zh.md", "", content="invalid!!!"),
            document("README.zh.md", "x" * 65537),
            document("README.zh.md", "hello", type="symlink"),
            document("../README.zh.md", "hello"),
            document("README.ja.md", "wrong requested path"),
        ]:
            with self.subTest(status=response.status_code, body=response.content[:80]):
                result, seen = await self.fetch(primary, response)
                self.assertEqual(len(seen), 3)
                self.assertEqual(result["readme_text"], primary)
                self.assertNotIn("readme_localized_path", result)

    async def test_valid_large_primary_readme_supplies_bounded_identity_excerpt(self):
        primary = "# Star Miner\nAn open source game.\n" + "Game details. " * 6000
        result, seen = await self.fetch(primary)
        self.assertEqual(len(seen), 2)
        self.assertEqual(result["readme_status"], "succeeded")
        self.assertEqual(result["readme_text"], primary[:12000])
        # The public response body limit is not raised for arbitrarily large
        # README JSON, nor is the optional translation limit relaxed.
        with self.assertRaises(service.DescriptionInputUnavailable):
            await self.fetch("x" * 300000)

    async def test_combined_input_remains_bounded_and_image_sources_are_not_rebound(self):
        primary = "# Project\n[中文](README.zh.md)\n![Cover](docs/cover.jpg)"
        translated = "![Cover](translated/cover.jpg)\n" + "中" * 15000
        result, seen = await self.fetch(primary, document("README.zh.md", translated))
        self.assertEqual(len(seen), 3)
        self.assertEqual(len(result["readme_text"]), 12000)
        self.assertEqual(len(result["image_candidates"]), 1)
        self.assertEqual(result["image_candidates"][0]["sourceUrl"], f"https://github.com/{REPO}/blob/main/README.md")
        self.assertEqual(result["image_candidates"][0]["url"], f"https://raw.githubusercontent.com/{REPO}/main/docs/cover.jpg")
