from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage

from backend.app.services.project_catalog.game_poster_agent import TOOLS, GamePosterAgent
from backend.app.services.project_catalog.game_poster_resources import PosterResource, PosterResourceError
from backend.tests.test_project_poster_coverage import cached_image
from backend.tests.test_project_web_posters import IMAGE, SOURCE, model_with, tool

ITEM = {"repo": "author/free-world", "detailsVersion": 1, "gameNameOriginal": "Commercial Classic"}
QUERY = '"free-world" author official website'
EMPTY = AIMessage(content='{"candidateId":""}')


def search_call(search_type=None, query=QUERY):
    args = {"query": query, "identityKind": "project"}
    if search_type is not None:
        args["searchType"] = search_type
    return tool("search_web", args)


class PosterSearchModeTests(unittest.IsolatedAsyncioTestCase):
    def test_search_mode_is_optional_in_existing_tool_contract(self):
        schema = TOOLS[0]["function"]["parameters"]
        self.assertEqual(schema["required"], ["query"])
        self.assertEqual(schema["properties"]["searchType"]["enum"], ["pages", "images"])
        self.assertFalse(schema["additionalProperties"])

    async def test_old_query_only_and_explicit_images_keep_existing_search(self):
        for args in ({"query": "Commercial Classic cover"}, {"query": "Commercial Classic cover", "searchType": "images"}):
            with self.subTest(args=args):
                images, pages = AsyncMock(return_value={"results": []}), AsyncMock()
                agent = GamePosterAgent(model_with(tool("search_web", args), EMPTY), search=images, search_pages=pages)
                result = await agent.run(ITEM)
                images.assert_awaited_once_with(args["query"])
                pages.assert_not_awaited()
                self.assertEqual(result["posterTrace"][0]["searchType"], "images")

    async def test_unrelated_image_results_can_switch_to_pages_then_verify_source(self):
        wrong = SOURCE + "/unrelated"
        model = model_with(search_call("images"), tool("read_page", {"resultId": "page-1"}),
                           search_call("pages"), tool("read_page", {"resultId": "page-2"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
                           AIMessage(content='{"candidateId":"image-1"}'))
        images = AsyncMock(return_value={"results": [{"url": wrong, "imageUrl": IMAGE}]})
        pages = AsyncMock(return_value={"results": [{"url": SOURCE, "title": "Free World official website"}]})
        fetch = AsyncMock(side_effect=[
            PosterResource(wrong, f'<h1>Another Game</h1><img src="{IMAGE}">'.encode(), "text/html"),
            PosterResource(SOURCE, f'<h1>Free World</h1><img src="{IMAGE}" alt="Gameplay">'.encode(), "text/html"),
            PosterResource(IMAGE, b"game pixels", "image/png"),
        ])
        review = AsyncMock(return_value={"matches": True, "kind": "screenshot", "reason": "matched"})
        agent = GamePosterAgent(model, search=images, search_pages=pages, fetch=fetch,
                                review=review, cache=AsyncMock(return_value=cached_image()))
        result = await agent.run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(result["posterSourceUrl"], SOURCE)
        self.assertEqual(result["posterTrace"][1]["candidateIds"], [])
        self.assertEqual(agent.counts, {"search_web": 2, "read_page": 2, "verify_image": 1})
        self.assertEqual(agent.limits, {"search_web": 2, "read_page": 6, "verify_image": 3})
        pages.assert_awaited_once_with(QUERY)
        review.assert_awaited_once()

    async def test_pages_search_cannot_skip_source_read_or_use_private_results(self):
        for source in (SOURCE, "http://127.0.0.1/internal"):
            with self.subTest(source=source):
                fetch, cache, review = AsyncMock(), AsyncMock(), AsyncMock()
                pages = AsyncMock(return_value={"results": [{"url": source, "imageUrl": IMAGE}]})
                model = model_with(search_call("pages"), tool("verify_image", {"candidateId": "image-1", "kind": "cover"}), EMPTY, EMPTY)
                result = await GamePosterAgent(model, search_pages=pages, fetch=fetch, review=review, cache=cache).run(ITEM)
                self.assertNotEqual(result["posterStatus"], "ready")
                self.assertEqual(result["posterTrace"][1]["error"], "unknown_candidate_id")
                fetch.assert_not_awaited()
                review.assert_not_awaited()
                cache.assert_not_awaited()
                if source != SOURCE:
                    self.assertEqual(result["posterTrace"][0]["results"], [])

    async def test_news_home_link_is_one_hop_and_destination_identity_is_rechecked(self):
        home = "https://freeworld.example/"
        article = f'<h1>Free World</h1><a href="{home}">Official project homepage</a>'.encode()
        for title, accepted in (("Free World", True), ("Another Game", False)):
            with self.subTest(title=title):
                target = f'<h1>{title}</h1><img src="{IMAGE}"><a href="https://github.com/author/free-world">Repository</a>'
                # On the unrelated page, even its image cannot become a known
                # candidate. Do not supply a matching repo link as evidence.
                if not accepted:
                    target = f'<h1>{title}</h1><img src="{IMAGE}">'
                model = model_with(search_call("pages"), tool("read_page", {"resultId": "page-1"}),
                                   tool("read_page", {"resultId": "page-2"}),
                                   tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
                                   AIMessage(content='{"candidateId":"image-1"}' if accepted else '{"candidateId":""}'))
                fetch = AsyncMock(side_effect=[PosterResource(SOURCE, article, "text/html"),
                                              PosterResource(home, target.encode(), "text/html"),
                                              PosterResource(IMAGE, b"game pixels", "image/png")])
                review = AsyncMock(return_value={"matches": True, "kind": "screenshot", "reason": "matched"})
                cache = AsyncMock(return_value=cached_image())
                agent = GamePosterAgent(model, search_pages=AsyncMock(return_value={"results": [{"url": SOURCE}]}),
                                        fetch=fetch, review=review, cache=cache)
                result = await agent.run(ITEM)
                self.assertEqual(result["posterTrace"][1]["linkedResults"][0]["url"], home)
                self.assertEqual(result["posterTrace"][2]["linkedResults"], [])
                self.assertEqual(result["posterTrace"][2]["parentResultId"], "page-1")
                if accepted:
                    self.assertEqual(result["posterStatus"], "ready")
                    self.assertEqual(result["posterSourceUrl"], home)
                    review.assert_awaited_once()
                else:
                    self.assertEqual(result["posterTrace"][2]["candidateIds"], [])
                    self.assertNotEqual(result["posterStatus"], "ready")
                    review.assert_not_awaited()
                    cache.assert_not_awaited()

    async def test_pages_search_keeps_game_and_sequel_query_guards(self):
        for args in ({"query": "Unrelated Project official", "identityKind": "project", "searchType": "pages"},
                     {"query": "Commercial Classic III cover", "searchType": "pages"}):
            with self.subTest(args=args):
                pages = AsyncMock()
                item = {**ITEM, "gameNameOriginal": "Commercial Classic II"}
                result = await GamePosterAgent(model_with(tool("search_web", args), EMPTY), search_pages=pages).run(item)
                pages.assert_not_awaited()
                self.assertEqual(result["posterTrace"][0]["error"], "query_must_include_game")

    async def test_invalid_search_mode_never_calls_either_provider(self):
        for mode in (None, "videos", [], {"pages": True}, 1):
            with self.subTest(mode=mode):
                args = {"query": QUERY, "identityKind": "project", "searchType": mode}
                images, pages = AsyncMock(), AsyncMock()
                result = await GamePosterAgent(model_with(tool("search_web", args), EMPTY), search=images, search_pages=pages).run(ITEM)
                self.assertEqual(result["posterTrace"][0]["error"], "query_must_include_game")
                images.assert_not_awaited()
                pages.assert_not_awaited()

    async def test_switching_search_modes_does_not_reset_budget(self):
        images, pages = AsyncMock(return_value={"results": []}), AsyncMock(return_value={"results": []})
        agent = GamePosterAgent(model_with(search_call("images"), search_call("pages"), search_call("images"), EMPTY),
                                search=images, search_pages=pages)
        result = await agent.run(ITEM)
        self.assertEqual(images.await_count, 1)
        self.assertEqual(pages.await_count, 1)
        self.assertEqual(agent.counts["search_web"], 2)
        self.assertEqual(result["posterTrace"][2]["error"], "tool_budget_exceeded")

    async def test_pages_can_use_existing_recovery_only_once(self):
        reads = AIMessage(content="", tool_calls=[
            {"name": "read_page", "args": {"resultId": "page-1"}, "id": "a", "type": "tool_call"},
            {"name": "read_page", "args": {"resultId": "page-2"}, "id": "b", "type": "tool_call"},
        ])
        model = model_with(search_call("images"), reads, search_call("images"), search_call("pages"), search_call("pages"), EMPTY)
        images = AsyncMock(side_effect=[{"results": [{"url": SOURCE}, {"url": SOURCE + "/other"}]}, {"results": []}])
        pages = AsyncMock(return_value={"results": []})
        agent = GamePosterAgent(model, search=images, search_pages=pages,
                                fetch=AsyncMock(side_effect=PosterResourceError("network_unavailable")))
        result = await agent.run(ITEM)
        self.assertEqual(images.await_count, 2)
        pages.assert_awaited_once_with(QUERY)
        self.assertEqual(agent.counts["search_web"], 3)
        self.assertEqual(agent.limits, {"search_web": 3, "read_page": 8, "verify_image": 4})
        self.assertTrue(result["posterTrace"][4]["sourceRecovery"])
        self.assertEqual(result["posterTrace"][5]["error"], "tool_budget_exceeded")

    async def test_page_provider_obeys_agent_deadline(self):
        async def blocked(query):
            await asyncio.Event().wait()

        result = await GamePosterAgent(model_with(search_call("pages")), search_pages=blocked, deadline_seconds=0.02).run(ITEM)
        self.assertEqual(result["posterStatus"], "unavailable")
        self.assertEqual(result["posterTrace"][0]["error"], "agent_deadline")

    async def test_external_cancellation_stops_page_provider(self):
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def blocked(query):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        agent = GamePosterAgent(model_with(search_call("pages")), search_pages=blocked)
        task = asyncio.create_task(agent.run(ITEM))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(cancelled.is_set())
