from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage, ToolMessage

from backend.app.services.project_catalog.game_poster_agent import GamePosterAgent, page_images
from backend.app.services.project_catalog.game_poster_resources import PosterResource, PosterResourceError
from backend.tests.test_project_poster_coverage import cached_image
from backend.tests.test_project_web_posters import IMAGE, SOURCE, model_with, tool

ITEM = {"repo": "author/free-world", "detailsVersion": 1, "gameNameOriginal": "Commercial Classic"}


class PosterSourceRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_project_query_can_include_verified_original_and_author_without_becoming_original_mode(self):
        query = '"free-world" author Commercial Classic screenshots'
        model = model_with(tool("search_web", {"query": query, "identityKind": "project"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
                           AIMessage(content='{"candidateId":"image-1"}'))
        fetch = AsyncMock(side_effect=[PosterResource(SOURCE, f'<h1>Free World</h1><img src="{IMAGE}">'.encode(), "text/html"),
                                      PosterResource(IMAGE, b"own game", "image/png")])
        review = AsyncMock(return_value={"matches": True, "kind": "screenshot", "reason": "matched"})
        result = await GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}),
                                      fetch=fetch, review=review, cache=AsyncMock(return_value=cached_image())).run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(result["posterTrace"][0]["identityKind"], "project")
        self.assertEqual(review.await_args.kwargs["candidate"]["identityKind"], "project")

    async def test_project_mode_cannot_search_an_unrelated_name(self):
        search = AsyncMock()
        model = model_with(tool("search_web", {"query": "Another Game screenshots", "identityKind": "project"}),
                           AIMessage(content='{"candidateId":""}'))
        result = await GamePosterAgent(model, search=search).run(ITEM)
        self.assertNotEqual(result["posterStatus"], "ready")
        search.assert_not_awaited()

    async def test_stale_index_does_not_displace_current_page_image(self):
        old = IMAGE + "?deleted=1"
        model = model_with(tool("search_web", {"query": "free-world screenshots"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
                           AIMessage(content='{"candidateId":"image-1"}'))
        fetch = AsyncMock(side_effect=[PosterResource(SOURCE, f'<h1>Free World</h1><img src="{IMAGE}" alt="Current gameplay">'.encode(), "text/html"),
                                      PosterResource(IMAGE, b"current image", "image/png")])
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE, "imageUrl": old}]}),
                                fetch=fetch, cache=AsyncMock(return_value=cached_image()))
        result = await agent.run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(agent.candidates["image-1"]["url"], IMAGE)
        self.assertTrue(agent.candidates["image-1"]["inSourcePage"])
        self.assertEqual(agent.candidates["image-2"]["url"], old)
        self.assertFalse(agent.candidates["image-2"]["inSourcePage"])
        self.assertNotIn(old, [call.args[0] for call in fetch.await_args_list])

    async def test_transient_sources_can_use_one_bounded_original_query_recovery(self):
        html = f'<h1>Commercial Classic</h1><img src="{IMAGE}">'.encode()
        model = model_with(
            tool("search_web", {"query": "Commercial Classic cover"}),
            AIMessage(content="", tool_calls=[
                {"name": "read_page", "args": {"resultId": "page-1"}, "id": "a", "type": "tool_call"},
                {"name": "read_page", "args": {"resultId": "page-2"}, "id": "b", "type": "tool_call"},
            ]),
            tool("search_web", {"query": "Commercial Classic screenshot"}),
            tool("read_page", {"resultId": "page-3"}),
            AIMessage(content='{"candidateId":""}'),
            tool("search_web", {"query": "Commercial Classic official game screenshot"}),
            tool("read_page", {"resultId": "page-4"}),
            tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
            AIMessage(content='{"candidateId":"image-1"}'),
        )
        search = AsyncMock(side_effect=[{"results": [{"url": SOURCE}, {"url": SOURCE + "/b"}]},
                                       {"results": [{"url": SOURCE + "/c"}]}, {"results": [{"url": SOURCE + "/d"}]}])
        fetch = AsyncMock(side_effect=[PosterResourceError("network_unavailable")] * 3
                         + [PosterResource(SOURCE + "/d", html, "text/html"), PosterResource(IMAGE, b"pixels", "image/png")])
        agent = GamePosterAgent(model, search=search, fetch=fetch, cache=AsyncMock(return_value=cached_image()))
        result = await agent.run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(search.await_count, 3)
        self.assertEqual(agent.limits, {"search_web": 3, "read_page": 8, "verify_image": 4})
        self.assertTrue(result["posterTrace"][5]["sourceRecovery"])
        self.assertFalse(agent._recovery_hint())

    async def test_wrong_project_picture_also_offers_disambiguated_recovery(self):
        model = model_with(tool("search_web", {"query": "free-world screenshots"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
                           AIMessage(content='{"candidateId":""}'), AIMessage(content='{"candidateId":""}'))
        fetch = AsyncMock(side_effect=[PosterResource(SOURCE, f'<h1>Free World</h1><img src="{IMAGE}">'.encode(), "text/html"),
                                      PosterResource(IMAGE, b"other game", "image/png")])
        cache = AsyncMock()
        model_review = AsyncMock(return_value={"matches": False, "kind": "cover", "reason": "wrong_game"})
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}),
                                fetch=fetch, review=model_review, cache=cache)
        result = await agent.run(ITEM)
        self.assertNotEqual(result["posterStatus"], "ready")
        self.assertTrue(agent.project_recovery)
        responses = [json.loads(message.content) for message in model.ainvoke.call_args.args[0] if isinstance(message, ToolMessage)]
        self.assertEqual(responses[2]["projectRecovery"]["projectRepo"], "author/free-world")
        cache.assert_not_awaited()


class WikiImageDetailTests(unittest.TestCase):
    def test_file_page_is_a_same_site_detail_link_not_an_image(self):
        source = "https://wiki.example.org/FreeWorld"
        body = b'<h1>FreeWorld</h1><a href="/File:FreeWorld.png"><img src="/images/thumb/FreeWorld.png" width="120"></a>'
        page = page_images(source, body, "FreeWorld", project_repo="author/freeworld")
        self.assertEqual(page["images"], [])
        self.assertEqual(page["links"], [{"url": "https://wiki.example.org/File:FreeWorld.png", "title": "游戏图片页面"}])
        detail = page_images(page["links"][0]["url"], b'<h1>File:FreeWorld.png</h1><a href="/images/ab/FreeWorld.png"><img src="/images/thumb/FreeWorld.png"></a>',
                             "FreeWorld", project_repo="author/freeworld")
        self.assertEqual(detail["images"][0]["url"], "https://wiki.example.org/images/ab/FreeWorld.png")

    def test_other_game_or_cross_site_file_page_cannot_expand_crawl(self):
        body = b'<h1>FreeWorld</h1><a href="https://other.example/File:FreeWorld.png">File</a><a href="/File:OtherGame.png">File</a>'
        page = page_images("https://wiki.example.org/FreeWorld", body, "FreeWorld", project_repo="author/freeworld")
        self.assertEqual(page["links"], [])
