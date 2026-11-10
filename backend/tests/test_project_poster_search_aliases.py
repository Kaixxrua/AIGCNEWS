from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage

from backend.app.services.project_catalog.game_poster_agent import GamePosterAgent, _platform_search_alias, page_images
from backend.app.services.project_catalog.game_poster_resources import PosterResource
from backend.tests.test_project_poster_coverage import cached_image
from backend.tests.test_project_web_posters import IMAGE, SOURCE, model_with, tool


class PosterSearchAliasTests(unittest.TestCase):
    def test_only_known_final_platform_parentheses_are_removed(self):
        for original, alias, platform in [
            ("The Legend of Zelda: Ocarina of Time (Nintendo Switch 2)", "The Legend of Zelda: Ocarina of Time", "Nintendo Switch 2"),
            ("DOOM II (Windows)", "DOOM II", "Windows"),
            ("A Game (1998 video game) (PlayStation 2)", "A Game (1998 video game)", "PlayStation 2"),
            ("A Game: Remastered (Linux)", "A Game: Remastered", "Linux"),
            ("冒险游戏（Nintendo Switch）", "冒险游戏", "Nintendo Switch"),
            ("A Game II (Nintendo Switch, 2019)", "A Game II (2019)", "Nintendo Switch"),
            ("A Game II (2019, Nintendo Switch)", "A Game II (2019)", "Nintendo Switch"),
            ("冒险游戏 II（Nintendo Switch，2019）", "冒险游戏 II (2019)", "Nintendo Switch"),
            ("Adventure II DS", "Adventure II", "DS"),
            ("Adventure II Nintendo 3DS", "Adventure II", "Nintendo 3DS"),
        ]:
            with self.subTest(original=original):
                self.assertEqual(_platform_search_alias(original), (alias, platform))
        for original in ["Doom (1993)", "Doom (2016 video game)", "Game (HD Edition)", "Game (Remastered)",
                         "Game (Nintendo Switch 2 remake)", "Game (Windows/Linux)", "PC", "Game (Unknown console)",
                         "Game (Nintendo Switch, 2019 remake)", "Game (Nintendo Switch, 2019, Remastered)"]:
            with self.subTest(original=original):
                self.assertIsNone(_platform_search_alias(original))

    def test_page_matching_uses_alias_without_losing_year_or_edition_evidence(self):
        def page(original, title):
            return page_images(SOURCE, f'<title>{title}</title><img src="{IMAGE}">'.encode(), original)

        self.assertTrue(page("DOOM II (Windows)", "DOOM II - Game Database")["matchesGame"])
        self.assertFalse(page("DOOM II (Windows)", "DOOM - Game Database")["matchesGame"])
        self.assertFalse(page("DOOM II (1994) (Windows)", "DOOM II")["matchesGame"])
        self.assertTrue(page("DOOM II (1994) (Windows)", "DOOM II (1994) for Windows")["matchesGame"])
        self.assertFalse(page("A Game (HD Edition)", "A Game")["matchesGame"])
        self.assertFalse(page("Diablo (Windows)", "Diablo II")["matchesGame"])

    def test_roman_and_arabic_sequels_match_only_the_same_number(self):
        for original, title in [("Adventure 2: New Lands", "Adventure II: New Lands"),
                                ("Adventure XIV", "Adventure 14"),
                                ("Adventure II", "Adventure Ⅱ™"),
                                ("Adventure I", "Adventure 1")]:
            with self.subTest(original=original, title=title):
                page = page_images(SOURCE, f'<h1>{title}</h1><img src="{IMAGE}">'.encode(), original)
                self.assertTrue(page["matchesGame"])
                self.assertTrue(page["images"])
        for title in ["Adventure I", "Adventure III", "Adventure 1", "Adventure 3", "Adventure 20"]:
            with self.subTest(title=title):
                body = f'<h1>{title}</h1><p>The sequel to Adventure II.</p><img src="{IMAGE}">'.encode()
                self.assertFalse(page_images(SOURCE, body, "Adventure II")["matchesGame"])
        self.assertFalse(page_images(SOURCE, f'<h1>Adventure 1009</h1><img src="{IMAGE}">'.encode(), "Adventure MIX")["matchesGame"])

    def test_platform_and_year_are_separate_but_required_page_evidence(self):
        original = "Adventure II (Nintendo Switch, 2019)"
        def page(platform="Nintendo Switch", year="2019", title="Adventure 2", extra=""):
            body = f'<h1>{title}</h1><p>Platform: {platform}</p><p>Released September {year}.</p>{extra}<img src="{IMAGE}">'.encode()
            return page_images(SOURCE, body, original)

        self.assertTrue(page()["matchesGame"])
        self.assertTrue(page(year="2019年")["matchesGame"])
        for changes in [{"year": ""}, {"platform": ""}, {"year": "2018"}, {"platform": "Nintendo Switch 2"},
                        {"title": "Adventure III", "extra": "<p>Inspired by Adventure II.</p>"},
                        {"year": "2018", "extra": "<footer>Copyright 2019</footer>"}]:
            with self.subTest(changes=changes):
                self.assertFalse(page(**changes)["matchesGame"])

    def test_separate_year_parentheses_require_the_same_version_evidence(self):
        body = f'<h1>Adventure II</h1><p>Release: 2019. Platform: Nintendo Switch.</p><img src="{IMAGE}">'.encode()
        self.assertTrue(page_images(SOURCE, body, "Adventure 2 (2019) (Nintendo Switch)")["matchesGame"])
        self.assertFalse(page_images(SOURCE, body, "Adventure 2 (2018) (Nintendo Switch)")["matchesGame"])
        self.assertFalse(page_images(SOURCE, body, "Adventure 2 (2019) (PlayStation 2)")["matchesGame"])

    def test_bare_console_suffix_needs_matching_page_platform(self):
        body = f'<h1>Adventure II.</h1><p>Platform: Nintendo DS.</p><img src="{IMAGE}">'.encode()
        self.assertTrue(page_images(SOURCE, body, "Adventure II DS")["matchesGame"])
        self.assertFalse(page_images(SOURCE, body, "Adventure II Nintendo 3DS")["matchesGame"])
        self.assertFalse(page_images(SOURCE, body.replace(b'Nintendo DS', b'Nintendo 3DS'), "Adventure II DS")["matchesGame"])
        self.assertFalse(page_images(SOURCE, body.replace(b'Platform: Nintendo DS.', b''), "Adventure II DS")["matchesGame"])


class PosterSearchAliasAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_alias_query_is_executed_and_original_platform_evidence_stays_in_model_input(self):
        original = "The Legend of Zelda: Ocarina of Time (Nintendo Switch 2)"
        alias = "The Legend of Zelda: Ocarina of Time"
        item = {"repo": "owner/project", "gameNameOriginal": original, "gameNameZh": "时之笛", "descriptionZh": "经典游戏移植项目。"}
        model = model_with(tool("search_web", {"query": alias + " cover"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
                           AIMessage(content='{"candidateId":"image-1"}'))
        search = AsyncMock(return_value={"results": [{"url": SOURCE}]})
        body = f'<h1>{alias}</h1><img src="{IMAGE}" alt="Original game cover">'.encode()
        fetch = AsyncMock(side_effect=[PosterResource(SOURCE, body, "text/html"), PosterResource(IMAGE, b"image", "image/png")])
        result = await GamePosterAgent(model, search=search, fetch=fetch, cache=AsyncMock(return_value=cached_image())).run(item)
        self.assertEqual(result["posterStatus"], "ready")
        search.assert_awaited_once_with(alias + " cover")
        payload = json.loads(model.ainvoke.await_args_list[0].args[0][1].content)
        self.assertEqual(payload["gameNameOriginal"], original)
        self.assertEqual(payload["searchIdentity"], alias)
        self.assertEqual(payload["platformEvidence"], "Nintendo Switch 2")
        self.assertEqual(item["gameNameOriginal"], original)
        self.assertNotIn("gameNameOriginal", result)

    async def test_chinese_query_is_repaired_to_safe_alias_instead_of_platform_suffix(self):
        model = model_with(tool("search_web", {"query": "时之笛封面 site:games.example.com"}), AIMessage(content='{"candidateId":""}'))
        search = AsyncMock(return_value={"results": []})
        await GamePosterAgent(model, search=search).run({
            "repo": "owner/project", "gameNameOriginal": "Ocarina of Time (Nintendo Switch 2)", "gameNameZh": "时之笛",
        })
        search.assert_awaited_once_with("Ocarina of Time cover site:games.example.com")

    async def test_alias_guard_does_not_authorize_dropping_sequel_edition_or_year(self):
        for original, query in [("DOOM II (Windows)", "DOOM cover"),
                                ("DOOM II (1994) (Windows)", "DOOM II cover"),
                                ("Game Remastered (Windows)", "Game cover"),
                                ("Adventure II (Nintendo Switch, 2019)", "Adventure 2 cover"),
                                ("Adventure II (Nintendo Switch, 2019)", "Adventure 3 cover 2019"),
                                ("Adventure II (Nintendo Switch, 2019)", "Adventure 1 cover 2019"),
                                ("Adventure II (Nintendo Switch, 2019)", "Adventure 2 cover 2018")]:
            with self.subTest(original=original):
                model = model_with(tool("search_web", {"query": query}), AIMessage(content='{"candidateId":""}'))
                search = AsyncMock()
                result = await GamePosterAgent(model, search=search).run({"gameNameOriginal": original})
                search.assert_not_awaited()
                self.assertEqual(result["posterTrace"][0]["error"], "query_must_include_game")

    async def test_version_search_accepts_word_order_without_dropping_the_year(self):
        for query in ["Adventure 2 cover 2019", "Adventure II 2019 cover", "Adventure II (2019) cover"]:
            with self.subTest(query=query):
                model = model_with(tool("search_web", {"query": query}), AIMessage(content='{"candidateId":""}'))
                search = AsyncMock(return_value={"results": []})
                await GamePosterAgent(model, search=search).run({"gameNameOriginal": "Adventure II (Nintendo Switch, 2019)"})
                search.assert_awaited_once_with(query)

    async def test_version_alias_keeps_full_original_identity_for_visual_review(self):
        original = "Adventure II (Nintendo Switch, 2019)"
        item = {"repo": "owner/project", "gameNameOriginal": original, "descriptionZh": "原作游戏移植项目。"}
        model = model_with(tool("search_web", {"query": "Adventure 2 cover 2019"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
                           AIMessage(content='{"candidateId":"image-1"}'))
        body = f'<h1>Adventure II</h1><p>Nintendo Switch. Released in 2019.</p><img src="{IMAGE}">'.encode()
        review = AsyncMock(return_value={"matches": True, "kind": "cover", "reason": "matched"})
        result = await GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}),
                                      fetch=AsyncMock(side_effect=[PosterResource(SOURCE, body, "text/html"), PosterResource(IMAGE, b"image", "image/png")]),
                                      review=review, cache=AsyncMock(return_value=cached_image())).run(item)
        self.assertEqual(result["posterStatus"], "ready")
        payload = json.loads(model.ainvoke.await_args_list[0].args[0][1].content)
        self.assertEqual(payload["gameNameOriginal"], original)
        self.assertEqual(payload["searchIdentity"], "Adventure II (2019)")
        self.assertEqual(payload["platformEvidence"], "Nintendo Switch")
        self.assertEqual(review.await_args.kwargs["item"]["gameNameOriginal"], original)
        self.assertEqual(item["gameNameOriginal"], original)

    async def test_verified_project_fallback_does_not_require_the_original_release_year(self):
        model = model_with(tool("search_web", {"query": "free-adventure screenshots"}), AIMessage(content='{"candidateId":""}'))
        search = AsyncMock(return_value={"results": []})
        await GamePosterAgent(model, search=search).run({"repo": "example/free-adventure", "detailsVersion": 1,
                                                       "gameNameOriginal": "Adventure II (Nintendo Switch, 2019)"})
        search.assert_awaited_once_with("free-adventure screenshots")


class PosterErrorFrameTests(unittest.IsolatedAsyncioTestCase):
    def assert_safe_frames(self, result):
        record = result["posterTrace"][-1]
        frames = record["errorFrames"]
        self.assertGreaterEqual(len(frames), 1)
        self.assertLessEqual(len(frames), 3)
        for frame in frames:
            self.assertEqual(set(frame), {"file", "function", "line"})
            self.assertNotIn("/", frame["file"])
            self.assertNotIn("\\", frame["file"])
            self.assertIsInstance(frame["line"], int)
            self.assertGreater(frame["line"], 0)
        self.assertNotIn("secret-provider-token", json.dumps(result))
        return frames

    async def test_tool_trace_has_three_frame_metadata_without_exception_text_or_locals(self):
        def innermost():
            secret = "secret-provider-token"
            raise RuntimeError(secret)

        def middle():
            innermost()

        async def search(query):
            middle()

        model = model_with(tool("search_web", {"query": "Diablo cover"}), AIMessage(content='{"candidateId":""}'))
        result = await GamePosterAgent(model, search=search).run({"gameNameOriginal": "Diablo"})
        frames = self.assert_safe_frames(result)
        self.assertEqual([frame["function"] for frame in frames], ["search", "middle", "innermost"])

    async def test_model_trace_uses_same_safe_frame_contract(self):
        async def fail(messages):
            raise RuntimeError("secret-provider-token")

        model = model_with()
        model.ainvoke = AsyncMock(side_effect=fail)
        result = await GamePosterAgent(model).run({"gameNameOriginal": "Diablo"})
        frames = self.assert_safe_frames(result)
        self.assertEqual(frames[-1]["function"], "fail")
        self.assertEqual(result["posterTrace"][-1]["stage"], "model_call")


if __name__ == "__main__":
    unittest.main()
