from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

from backend.app.services.project_catalog import game_poster_resources as resources
from backend.app.services.project_catalog.game_poster_agent import GamePosterAgent, page_images
from backend.app.services.project_catalog.game_poster_resources import PosterResource
from backend.tests.test_project_web_posters import HTML, IMAGE, ITEM, ORIGINAL, SOURCE, image_bytes, model_with, tool


class ProjectPosterIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_multi_game_projects_search_the_project_without_inventing_an_original(self):
        for repo, name, source in [("openra/openra", "OpenRA", "https://www.openra.net/"),
                                   ("scummvm/scummvm", "ScummVM", "https://www.scummvm.org/")]:
            with self.subTest(repo=repo), tempfile.TemporaryDirectory() as directory, patch.object(resources.settings, "site_assets_storage_dir", directory):
                item = {"repo": repo, "detailsVersion": 1, "gameNameOriginal": "", "gameNameZh": "", "descriptionZh": "可运行多款经典游戏的开源项目。"}
                image = source + "screenshots/gameplay.jpg"
                body = f'<title>{name}</title><h1>{name}</h1><p>The open source project.</p><img src="{image}" alt="{name} gameplay"><a href="https://github.com/{repo}">Source</a>'.encode()
                model = model_with(
                    tool("search_web", {"query": name + " screenshots"}),
                    tool("read_page", {"resultId": "page-1"}),
                    tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
                    AIMessage(content='{"candidateId":"image-1"}'),
                )
                search = AsyncMock(return_value={"results": [{"url": source, "title": name}]})
                fetch = AsyncMock(side_effect=[PosterResource(source, body, "text/html"), PosterResource(image, image_bytes(), "image/jpeg")])
                result = await GamePosterAgent(model, search=search, fetch=fetch).run(item)
                self.assertEqual(result["posterStatus"], "ready")
                self.assertEqual(result["posterKind"], "screenshot")
                self.assertEqual(result["posterSourceUrl"], source)
                search.assert_awaited_once_with(name + " screenshots")
                payload = json.loads(model.ainvoke.await_args_list[0].args[0][1].content)
                self.assertEqual(payload["identityKind"], "project")
                self.assertEqual(payload["searchIdentity"], repo.split("/")[1])
                self.assertEqual(payload["gameNameOriginal"], "")
                self.assertEqual(item["gameNameOriginal"], "")
                self.assertNotIn("gameNameOriginal", result)

    async def test_fallback_requires_a_previously_enriched_valid_repository(self):
        for item in [{"repo": "openra/openra"}, {"repo": "https://github.com/openra/openra", "detailsVersion": 1},
                     {"repo": "owner/../openra", "detailsVersion": 1}, {"repo": "", "detailsVersion": 1}]:
            search = AsyncMock()
            model = model_with()
            result = await GamePosterAgent(model, search=search).run(item)
            self.assertEqual(result["posterStatus"], "missing")
            search.assert_not_awaited()
            model.ainvoke.assert_not_awaited()

    async def test_project_mode_cannot_search_only_one_supported_commercial_game(self):
        model = model_with(tool("search_web", {"query": "Red Alert cover"}), AIMessage(content='{"candidateId":""}'))
        search = AsyncMock()
        result = await GamePosterAgent(model, search=search).run({
            "repo": "openra/openra", "detailsVersion": 1, "gameNameOriginal": "", "gameNameZh": "红色警戒",
        })
        search.assert_not_awaited()
        self.assertEqual(result["posterStatus"], "unavailable")
        self.assertNotIn("posterUrl", result)

    def test_project_page_needs_project_title_or_verified_repository_link(self):
        body = b'<title>Red Alert</title><h1>Red Alert</h1><p>Also supported by OpenRA.</p><img src="https://example.com/red-alert-cover.jpg">'
        rejected = page_images("https://example.com/red-alert", body, "openra", project_repo="openra/openra")
        self.assertFalse(rejected["matchesGame"])
        self.assertEqual(rejected["images"], [])
        linked = b'<title>Classic RTS rebuilt</title><p>OpenRA is an open source strategy game engine.</p><a href="https://github.com/openra/openra">Project source</a><img src="https://example.com/gameplay.jpg">'
        self.assertTrue(page_images("https://example.com/project", linked, "openra", project_repo="openra/openra")["matchesGame"])


class PosterTurnLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_final_turn_verified_image_does_not_require_an_extra_model_call(self):
        model = model_with(
            tool("search_web", {"query": ORIGINAL + " cover"}),
            tool("read_page", {"resultId": "page-1"}),
            tool("search_web", {"query": ORIGINAL + " cover site:example.com"}),
            tool("read_page", {"resultId": "page-2"}),
            tool("read_page", {"resultId": "page-3"}),
            tool("read_page", {"resultId": "page-4"}),
            tool("read_page", {"resultId": "page-5"}),
            tool("verify_image", {"candidateId": "image-5", "kind": "cover"}),
        )
        search = AsyncMock(return_value={"results": [{"url": SOURCE + str(index)} for index in range(5)]})
        fetch = AsyncMock(side_effect=[*[PosterResource(SOURCE + str(index), HTML, "text/html") for index in range(5)], PosterResource(IMAGE, image_bytes(), "image/png")])
        with tempfile.TemporaryDirectory() as directory, patch.object(resources.settings, "site_assets_storage_dir", directory):
            result = await GamePosterAgent(model, search=search, fetch=fetch).run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(result["posterSourceUrl"], SOURCE + "4")
        self.assertEqual(model.ainvoke.await_count, 8)
        self.assertEqual(result["posterTrace"][-1]["selectionReason"], "model_turn_limit")

    async def test_explicit_empty_final_candidate_does_not_get_replaced_with_verified_image(self):
        model = model_with(
            tool("search_web", {"query": ORIGINAL + " cover"}),
            tool("read_page", {"resultId": "page-1"}),
            tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
            tool("search_web", {"query": ORIGINAL + " screenshots"}),
            tool("read_page", {"resultId": "page-2"}),
            AIMessage(content='{"candidateId":""}'),
        )
        search = AsyncMock(side_effect=[{"results": [{"url": SOURCE}]}, {"results": [{"url": SOURCE + "/screenshots"}]}])
        fetch = AsyncMock(side_effect=[PosterResource(SOURCE, HTML, "text/html"), PosterResource(IMAGE, image_bytes(), "image/png"), PosterResource(SOURCE + "/screenshots", HTML, "text/html")])
        with tempfile.TemporaryDirectory() as directory, patch.object(resources.settings, "site_assets_storage_dir", directory):
            result = await GamePosterAgent(model, search=search, fetch=fetch).run(ITEM)
        self.assertEqual(result["posterStatus"], "missing")
        self.assertNotIn("posterUrl", result)
        self.assertEqual(model.ainvoke.await_count, 6)

    async def test_last_turn_unverified_or_failed_image_is_never_selected(self):
        for payload in [b"<html>image download failed</html>", b""]:
            model = model_with(
                tool("search_web", {"query": ORIGINAL + " cover"}),
                tool("read_page", {"resultId": "page-1"}),
                tool("search_web", {"query": ORIGINAL + " screenshots"}),
                tool("read_page", {"resultId": "page-2"}),
                tool("read_page", {"resultId": "page-3"}),
                tool("verify_image", {"candidateId": "image-3", "kind": "cover"}),
            )
            search = AsyncMock(side_effect=[{"results": [{"url": SOURCE}]}, {"results": [{"url": SOURCE + "/screenshots"}, {"url": SOURCE + "/covers"}]}])
            fetch = AsyncMock(side_effect=[PosterResource(SOURCE, HTML, "text/html")] * 3 + [PosterResource(IMAGE, payload, "image/png")])
            result = await GamePosterAgent(model, search=search, fetch=fetch).run(ITEM)
            self.assertEqual(result["posterStatus"], "unavailable")
            self.assertNotIn("posterUrl", result)


class PosterAgentDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_exception_trace_records_only_safe_class_name(self):
        model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}), AIMessage(content='{"candidateId":""}'))
        search = AsyncMock(side_effect=RuntimeError("private provider secret, never expose"))
        result = await GamePosterAgent(model, search=search).run(ITEM)
        self.assertEqual(result["posterStatus"], "unavailable")
        self.assertEqual(result["posterTrace"][0]["errorType"], "RuntimeError")
        self.assertEqual(result["posterTrace"][0]["error"], "tool_unavailable")
        self.assertNotIn("private provider secret", json.dumps(result))

    async def test_model_binding_and_call_exception_stage_are_distinguished_without_message(self):
        for phase in ("model_bind", "model_call"):
            model = model_with()
            failure = RuntimeError("private model token, never expose")
            if phase == "model_bind":
                model.bind_tools.side_effect = failure
            else:
                model.ainvoke.side_effect = failure
            result = await GamePosterAgent(model).run(ITEM)
            self.assertEqual(result["posterStatus"], "unavailable")
            self.assertEqual(result["posterTrace"][-1]["stage"], phase)
            self.assertEqual(result["posterTrace"][-1]["errorType"], "RuntimeError")
            self.assertNotIn("private model token", json.dumps(result))
