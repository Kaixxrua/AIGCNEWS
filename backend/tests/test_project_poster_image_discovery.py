from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage, ToolMessage

from backend.app.services.project_catalog.game_poster_agent import GamePosterAgent
from backend.app.services.project_catalog.game_poster_resources import PosterResource, PosterResourceError
from backend.tests.test_project_poster_coverage import cached_image
from backend.tests.test_project_web_posters import IMAGE, SOURCE, model_with, tool

ITEM = {"repo": "example/free-world", "detailsVersion": 1, "gameNameOriginal": "Commercial Classic",
        "descriptionZh": "使用自由素材的独立游戏。"}
PAGE = b'<h1>Free World</h1><p>Open source game.</p>'


class ImageDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_image_search_requires_read_source_and_verified_pixels_before_caching(self):
        model = model_with(tool("search_web", {"query": "free-world screenshots"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
                           AIMessage(content='{"candidateId":"image-1"}'))
        search = AsyncMock(return_value={"results": [{"url": SOURCE, "imageUrl": IMAGE, "title": "Free World gameplay"}]})
        body = PAGE + f'<img src="{IMAGE}" alt="Actual game battle" width="800" height="600">'.encode()
        fetch = AsyncMock(side_effect=[PosterResource(SOURCE, body, "text/html"), PosterResource(IMAGE, b"pixels", "image/png")])
        review = AsyncMock(return_value={"matches": True, "kind": "screenshot", "reason": "matched"})
        cache = AsyncMock(return_value=cached_image())
        result = await GamePosterAgent(model, search=search, fetch=fetch, review=review, cache=cache).run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(result["posterSourceUrl"], SOURCE)
        self.assertEqual([call.args[0] for call in fetch.await_args_list], [SOURCE, IMAGE])
        self.assertEqual(review.await_args.kwargs["candidate"]["discoveredBy"], "image_search")
        self.assertEqual(review.await_args.kwargs["candidate"]["label"], "Actual game battle")
        self.assertEqual(review.await_args.kwargs["candidate"]["width"], 800)
        cache.assert_awaited_once_with(b"pixels")

    async def test_indexed_image_never_bypasses_mismatching_or_failed_source_page(self):
        for source in [PosterResource(SOURCE, b'<h1>Another Game</h1>', "text/html"), PosterResourceError("page_unavailable")]:
            with self.subTest(source=type(source).__name__):
                model = model_with(tool("search_web", {"query": "free-world screenshots"}),
                                   tool("read_page", {"resultId": "page-1"}),
                                   tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
                                   AIMessage(content='{"candidateId":""}'))
                fetch, cache, review = AsyncMock(side_effect=[source]), AsyncMock(), AsyncMock()
                agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE, "imageUrl": IMAGE}]}),
                                        fetch=fetch, cache=cache, review=review)
                result = await agent.run(ITEM)
                self.assertNotEqual(result["posterStatus"], "ready")
                fetch.assert_awaited_once_with(SOURCE)
                cache.assert_not_awaited()
                review.assert_not_awaited()

    async def test_new_indexed_images_reparse_same_source_without_refetch_and_keep_distinct_images(self):
        model = model_with(tool("search_web", {"query": "free-world screenshots"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("search_web", {"query": "free-world game screenshot"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-2", "kind": "screenshot"}),
                           AIMessage(content='{"candidateId":"image-2"}'))
        second = IMAGE + "?second=1"
        search = AsyncMock(side_effect=[{"results": [{"url": SOURCE}]}, {"results": [
            {"url": SOURCE, "imageUrl": IMAGE}, {"url": SOURCE, "imageUrl": second},
            {"url": SOURCE, "imageUrl": IMAGE}, {"url": SOURCE, "imageUrl": "https://127.0.0.1/private"},
        ]}])
        fetch = AsyncMock(side_effect=[PosterResource(SOURCE, PAGE, "text/html"), PosterResource(second, b"pixels", "image/png")])
        agent = GamePosterAgent(model, search=search, fetch=fetch, cache=AsyncMock(return_value=cached_image()))
        result = await agent.run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(agent.counts["read_page"], 1)
        self.assertEqual(len(agent.results), 1)
        self.assertEqual(len(agent.candidates), 2)
        self.assertTrue(result["posterTrace"][3]["reusedPage"])

    async def test_wrong_original_can_use_one_bounded_project_recovery_after_search_budget(self):
        project = SOURCE + "/project"
        original_page = f'<h1>Commercial Classic</h1><img src="{IMAGE}">'.encode()
        calls = [
            tool("search_web", {"query": "Commercial Classic cover"}),
            tool("read_page", {"resultId": "page-1"}),
            tool("search_web", {"query": "Commercial Classic images"}),
            tool("read_page", {"resultId": "page-2"}),
            tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
            tool("verify_image", {"candidateId": "image-2", "kind": "cover"}),
            tool("search_web", {"query": "Commercial Classic cover again"}),
            tool("search_web", {"query": "free-world screenshots"}),
            AIMessage(content="", tool_calls=[
                {"name": "read_page", "args": {"resultId": "page-3"}, "id": "project", "type": "tool_call"},
                {"name": "search_web", "args": {"query": "free-world screenshots extra"}, "id": "overflow", "type": "tool_call"},
            ]),
            tool("verify_image", {"candidateId": "image-3", "kind": "screenshot"}),
            AIMessage(content='{"candidateId":"image-3"}'),
        ]
        model = model_with(*calls)
        search = AsyncMock(side_effect=[{"results": [{"url": SOURCE}]}, {"results": [{"url": SOURCE + "/two"}]},
                                       {"results": [{"url": project, "imageUrl": IMAGE}]}])
        fetch = AsyncMock(side_effect=[PosterResource(SOURCE, original_page, "text/html"),
                                      PosterResource(SOURCE + "/two", original_page, "text/html"),
                                      PosterResource(IMAGE, b"wrong", "image/png"), PosterResource(IMAGE, b"wrong", "image/png"),
                                      PosterResource(project, PAGE, "text/html"), PosterResource(IMAGE, b"own game", "image/png")])
        review = AsyncMock(side_effect=[{"matches": False, "kind": "cover", "reason": "wrong_game"}] * 2
                               + [{"matches": True, "kind": "screenshot", "reason": "matched"}])
        cache = AsyncMock(return_value=cached_image())
        agent = GamePosterAgent(model, search=search, fetch=fetch, review=review, cache=cache)
        result = await agent.run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(model.ainvoke.await_count, 11)
        self.assertEqual(search.await_count, 3)
        self.assertEqual(agent.limits, {"search_web": 3, "read_page": 8, "verify_image": 4})
        self.assertEqual(result["posterTrace"][6]["error"], "recovery_requires_project_query")
        self.assertEqual(result["posterTrace"][9]["error"], "tool_budget_exceeded")
        frames = [json.loads(m.content) for m in model.ainvoke.call_args.args[0] if isinstance(m, ToolMessage)]
        self.assertEqual(frames[4]["projectRecovery"]["queryIdentity"], "free-world")
        cache.assert_awaited_once_with(b"own game")

    async def test_new_search_keeps_new_images_when_same_page_already_has_six_old_candidates(self):
        model = model_with(tool("search_web", {"query": "free-world screenshots"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("search_web", {"query": "free-world actual gameplay"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-7", "kind": "screenshot"}),
                           AIMessage(content='{"candidateId":"image-7"}'))
        old = [{"url": SOURCE, "imageUrl": IMAGE + "?old=" + str(index)} for index in range(6)]
        fresh = IMAGE + "?new=1"
        search = AsyncMock(side_effect=[{"results": old}, {"results": [{"url": SOURCE, "imageUrl": fresh}]}])
        fetch = AsyncMock(side_effect=[PosterResource(SOURCE, PAGE, "text/html"), PosterResource(fresh, b"fresh pixels", "image/png")])
        agent = GamePosterAgent(model, search=search, fetch=fetch, cache=AsyncMock(return_value=cached_image()))
        result = await agent.run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(agent.counts["read_page"], 1)
        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(agent.candidates["image-7"]["url"], fresh)
        first = result["posterTrace"][0]["results"][0]["searchImages"]
        self.assertEqual([row["url"] for row in first], [row["imageUrl"] for row in old])
        self.assertEqual(len(agent.results["page-1"]["searchImages"]), 6)


if __name__ == "__main__":
    unittest.main()
