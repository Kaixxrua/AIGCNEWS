from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage, ToolMessage

from backend.app.services.project_catalog.game_poster_agent import GamePosterAgent, page_images
from backend.app.services.project_catalog.game_poster_resources import ASSET_BASE, PosterResource
from backend.tests.test_project_web_posters import HTML, IMAGE, ITEM, ORIGINAL, SOURCE, model_with, tool


def cached_image():
    return {"url": ASSET_BASE + "a" * 64 + ".jpg", "sha256": "a" * 64, "width": 240, "height": 360}


def tool_results(model):
    return [json.loads(message.content) for message in model.ainvoke.call_args.args[0] if isinstance(message, ToolMessage)]


class PosterCoveragePagesTests(unittest.TestCase):
    def test_candidates_include_linked_full_size_images_and_local_context(self):
        body = (f'<title>{ORIGINAL}</title><h2>Box front</h2><figure>'
                '<a href="/large-cover.jpg"><img src="/thumbnail.jpg" width="80" height="100" alt="US release"></a>'
                '<figcaption>Windows retail cover</figcaption></figure>'
                '<h2>Screenshots</h2><img src="/gameplay.jpg" width="640" height="480" alt="In-game view">').encode()
        page = page_images(SOURCE, body, ORIGINAL)
        self.assertEqual(len(page["images"]), 2)
        cover, screenshot = page["images"]
        self.assertEqual(cover["url"], "https://store.example.com/large-cover.jpg")
        self.assertTrue(cover["linkedOriginal"])
        self.assertEqual(cover["context"], "Box front")
        self.assertIn("Windows retail cover", cover["label"])
        self.assertNotIn("width", cover)  # Thumbnail dimensions are not the original's.
        self.assertEqual((screenshot["width"], screenshot["height"]), (640, 480))

    def test_only_matching_same_site_gallery_links_are_exposed(self):
        source = "https://games.example.com/game/123/diablo"
        body = b'''<title>Diablo</title><h1>Diablo</h1>
          <a href="/game/123/diablo/covers">Covers</a>
          <a href="/games/images/123-diablo">Images</a>
          <a href="https://evil.example.org/diablo/covers">Diablo covers</a>
          <a href="/game/456/diablo-ii/covers">Diablo II covers</a>
          <a href="/game/456/unrelated/covers">Covers</a>
          <a href="https://127.0.0.1/diablo/covers">Diablo covers</a>
          <a href="/game/123/diablo/covers#front">Covers duplicate</a>
          <a href="/game/123/diablo/reviews">Reviews</a>'''
        page = page_images(source, body, "Diablo")
        self.assertEqual([row["url"] for row in page["links"]], [
            "https://games.example.com/game/123/diablo/covers", "https://games.example.com/games/images/123-diablo",
        ])

    def test_obvious_numbered_sequel_cannot_approve_base_game_images(self):
        for name in ("Diablo II", "Diablo 4", "Diablo III - MobyGames"):
            page = page_images(SOURCE, f'<title>{name}</title><p>The sequel to Diablo.</p><img src="/cover.jpg">'.encode(), "Diablo")
            self.assertFalse(page["matchesGame"])
            self.assertEqual(page["images"], [])
            self.assertEqual(page["links"], [])
        self.assertTrue(page_images(SOURCE, b'<title>Diablo</title><img src="/cover.jpg">', "Diablo")["matchesGame"])

    def test_malformed_unrelated_link_cannot_hide_valid_artwork(self):
        body = HTML + b'<a href="https://[invalid/covers"><img src="https://[invalid/image.png"></a>'
        self.assertEqual([image["url"] for image in page_images(SOURCE, body, ORIGINAL)["images"]], [IMAGE])


class PosterCoverageAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_reads_overlap_and_ids_follow_model_order_not_network_order(self):
        first, second = asyncio.Event(), asyncio.Event()
        sources = [SOURCE + "/first", SOURCE + "/second"]
        images = [IMAGE + "?first", IMAGE + "?second"]

        async def fetch(url, *, image=False):
            if image:
                return PosterResource(url, b"decoded-by-cache", "image/png")
            index = sources.index(url)
            (first if index == 0 else second).set()
            await asyncio.wait_for((second if index == 0 else first).wait(), 0.5)
            if index == 0:
                await asyncio.sleep(0.02)
            return PosterResource(url, HTML.replace(IMAGE.encode(), images[index].encode()), "text/html")

        reads = AIMessage(content="", tool_calls=[
            {"name": "read_page", "args": {"resultId": "page-1"}, "id": "first", "type": "tool_call"},
            {"name": "read_page", "args": {"resultId": "page-2"}, "id": "second", "type": "tool_call"},
        ])
        model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}), reads,
                           tool("verify_image", {"candidateId": "image-1", "kind": "cover"}), AIMessage(content='{"candidateId":"image-1"}'))
        search = AsyncMock(return_value={"results": [{"url": source} for source in sources]})
        fetch_mock = AsyncMock(side_effect=fetch)
        result = await GamePosterAgent(model, search=search, fetch=fetch_mock, cache=AsyncMock(return_value=cached_image())).run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(result["posterSourceUrl"], sources[0])
        fetch_mock.assert_any_await(images[0], image=True)
        reads = [row for row in result["posterTrace"] if row["tool"] == "read_page"]
        self.assertEqual([row["resultId"] for row in reads], ["page-1", "page-2"])
        self.assertEqual([row["candidateIds"] for row in reads], [["image-1"], ["image-2"]])
        candidate = next(row["candidates"][0] for row in tool_results(model) if "candidates" in row)
        self.assertEqual(candidate["imageUrl"], images[0])
        self.assertEqual(candidate["pageTitle"], ORIGINAL)
        self.assertEqual(candidate["sourceUrl"], sources[0])

    async def test_gallery_hop_retains_provenance_and_cannot_open_a_second_hop(self):
        gallery = SOURCE + "/covers"
        second_hop = gallery + "/gallery"
        body = f'<h1>{ORIGINAL}</h1><a href="{gallery}">Covers</a>'.encode()
        gallery_body = HTML + f'<a href="{second_hop}">More cover images</a>'.encode()
        model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("read_page", {"resultId": "page-2"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "cover"}), AIMessage(content='{"candidateId":"image-1"}'))
        search = AsyncMock(return_value={"results": [{"url": SOURCE}]})
        fetch = AsyncMock(side_effect=[PosterResource(SOURCE, body, "text/html"), PosterResource(gallery, gallery_body, "text/html"),
                                      PosterResource(IMAGE, b"image", "image/png")])
        agent = GamePosterAgent(model, search=search, fetch=fetch, cache=AsyncMock(return_value=cached_image()))
        result = await agent.run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(result["posterSourceUrl"], gallery)
        self.assertEqual(agent.counts["read_page"], 2)
        self.assertEqual(result["posterTrace"][2]["parentResultId"], "page-1")
        self.assertNotIn(second_hop, [row["url"] for row in agent.results.values()])

    async def test_same_turn_cannot_guess_ids_that_have_not_been_returned(self):
        calls = AIMessage(content="", tool_calls=[
            {"name": "search_web", "args": {"query": ORIGINAL + " cover"}, "id": "search", "type": "tool_call"},
            {"name": "read_page", "args": {"resultId": "page-1"}, "id": "guess", "type": "tool_call"},
        ])
        model = model_with(calls, AIMessage(content='{"candidateId":""}'))
        fetch = AsyncMock()
        result = await GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}), fetch=fetch).run(ITEM)
        fetch.assert_not_awaited()
        self.assertEqual(result["posterTrace"][1]["error"], "unknown_result_id")

    async def test_parallel_calls_still_enforce_the_shared_page_budget(self):
        calls = AIMessage(content="", tool_calls=[
            {"name": "read_page", "args": {"resultId": f"page-{index + 1}"}, "id": str(index), "type": "tool_call"} for index in range(6)
        ])
        model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}),
                           tool("search_web", {"query": ORIGINAL + " screenshots"}), calls,
                           tool("read_page", {"resultId": "page-7"}), AIMessage(content='{"candidateId":""}'))
        # Different hosts exercise the global six-page budget independently
        # of the per-host limit on probes still waiting for a response.
        search = AsyncMock(side_effect=[{"results": [{"url": f"https://source{index}.example/game"} for index in range(6)]},
                                       {"results": [{"url": "https://source6.example/game"}]}])
        fetch = AsyncMock(return_value=PosterResource(SOURCE, HTML, "text/html"))
        result = await GamePosterAgent(model, search=search, fetch=fetch).run(ITEM)
        self.assertEqual(fetch.await_count, 6)
        self.assertEqual(result["posterTrace"][-1]["error"], "tool_budget_exceeded")

    async def test_model_failure_after_verified_image_keeps_real_evidence(self):
        for final, phase in [(RuntimeError("private token"), "model_call"), (AIMessage(content="{truncated response"), "model_response")]:
            with self.subTest(phase=phase):
                model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}),
                                   tool("read_page", {"resultId": "page-1"}),
                                   tool("verify_image", {"candidateId": "image-1", "kind": "cover"}), final)
                result = await GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}),
                                              fetch=AsyncMock(side_effect=[PosterResource(SOURCE, HTML, "text/html"), PosterResource(IMAGE, b"image", "image/png")]),
                                              cache=AsyncMock(return_value=cached_image())).run(ITEM)
                self.assertEqual(result["posterStatus"], "ready")
                self.assertEqual(result["posterTrace"][-1]["stage"], phase)
                self.assertEqual(result["posterTrace"][-2]["selectionReason"], "agent_unavailable")
                self.assertNotIn("private token", json.dumps(result))

    async def test_deadline_retains_tool_trace_and_distinguishes_model_timeout(self):
        async def blocked(*args):
            await asyncio.Event().wait()

        model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}))
        result = await GamePosterAgent(model, search=AsyncMock(side_effect=blocked), deadline_seconds=0.02).run(ITEM)
        self.assertEqual(result["posterStatus"], "unavailable")
        self.assertEqual(result["posterTrace"][0]["error"], "agent_deadline")
        self.assertIn("elapsedMs", result["posterTrace"][0])
        self.assertEqual(result["posterTrace"][-1]["error"], "agent_deadline")
        model = model_with()
        model.ainvoke = AsyncMock(side_effect=blocked)
        result = await GamePosterAgent(model, model_seconds=0.01).run(ITEM)
        self.assertEqual(result["posterTrace"][-1]["error"], "model_timeout")

    async def test_deadline_after_verification_keeps_the_cached_poster(self):
        responses = iter([tool("search_web", {"query": ORIGINAL + " cover"}),
                          tool("read_page", {"resultId": "page-1"}),
                          tool("verify_image", {"candidateId": "image-1", "kind": "cover"})])

        async def respond(messages):
            try:
                return next(responses)
            except StopIteration:
                await asyncio.Event().wait()

        model = model_with()
        model.ainvoke = AsyncMock(side_effect=respond)
        result = await GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}),
                                      fetch=AsyncMock(side_effect=[PosterResource(SOURCE, HTML, "text/html"), PosterResource(IMAGE, b"image", "image/png")]),
                                      cache=AsyncMock(return_value=cached_image()), deadline_seconds=0.05).run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(result["posterTrace"][-1]["error"], "agent_deadline")
        self.assertEqual(result["posterTrace"][-2]["selectionReason"], "agent_deadline")

    async def test_external_cancellation_stops_all_parallel_page_requests(self):
        started, cancelled = set(), set()
        both_started = asyncio.Event()

        async def fetch(url):
            started.add(url)
            if len(started) == 2:
                both_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.add(url)
                raise

        reads = AIMessage(content="", tool_calls=[
            {"name": "read_page", "args": {"resultId": "page-1"}, "id": "first", "type": "tool_call"},
            {"name": "read_page", "args": {"resultId": "page-2"}, "id": "second", "type": "tool_call"},
        ])
        model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}), reads)
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE + "/first"}, {"url": SOURCE + "/second"}]}), fetch=fetch)
        task = asyncio.create_task(agent.run(ITEM))
        await asyncio.wait_for(both_started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(cancelled, started)
        self.assertEqual(model.ainvoke.await_count, 2)


if __name__ == "__main__":
    unittest.main()
