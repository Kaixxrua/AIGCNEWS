from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend.app.services.project_catalog.game_poster_agent import GamePosterAgent, page_images
from backend.app.services.project_catalog.game_poster_resources import PosterResource, PosterResourceError
from backend.tests.test_project_poster_coverage import cached_image
from backend.tests.test_project_web_posters import HTML, IMAGE, ITEM, ORIGINAL, SOURCE, model_with, tool


class PosterRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_search_results_do_not_reintroduce_failed_urls_as_new_sources(self):
        model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("search_web", {"query": ORIGINAL + " box art"}),
                           AIMessage(content='{"candidateId":""}'))
        search = AsyncMock(return_value={"results": [{"url": SOURCE}, {"url": SOURCE + "#duplicate"}]})
        agent = GamePosterAgent(model, search=search, fetch=AsyncMock(side_effect=PosterResourceError("page_unavailable")))
        result = await agent.run(ITEM)
        self.assertEqual(result["posterStatus"], "unavailable")
        self.assertEqual(len(agent.results), 1)
        self.assertEqual(agent._unused_pages(), [])
        self.assertEqual(model.ainvoke.await_count, 4)
        self.assertTrue(result["posterTrace"][2]["results"][0]["alreadyRead"])

    async def test_search_failure_preserves_unread_sources_and_empty_reply_gets_one_recovery_turn(self):
        other = "https://covers.example.org/game"
        model = model_with(
            tool("search_web", {"query": ORIGINAL + " cover"}),
            tool("read_page", {"resultId": "page-1"}),
            tool("search_web", {"query": ORIGINAL + " cover site:games.example.org"}),
            AIMessage(content='{"candidateId":""}'),
            tool("read_page", {"resultId": "page-2"}),
            tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
        )
        search = AsyncMock(side_effect=[{"results": [{"url": SOURCE}, {"url": other}]}, PosterResourceError("search_unavailable")])
        fetch = AsyncMock(side_effect=[PosterResourceError("page_unavailable"), PosterResource(other, HTML, "text/html"),
                                      PosterResource(IMAGE, b"image", "image/png")])
        result = await GamePosterAgent(model, search=search, fetch=fetch, cache=AsyncMock(return_value=cached_image())).run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(result["posterSourceUrl"], other)
        failure = result["posterTrace"][1]
        self.assertEqual(failure["sourceUrl"], SOURCE)
        self.assertEqual(failure["resultId"], "page-1")
        messages = model.ainvoke.call_args.args[0]
        failed_search = [json.loads(message.content) for message in messages if isinstance(message, ToolMessage)][2]
        self.assertEqual(failed_search["unreadSources"][0]["url"], other)
        recoveries = [message for message in messages if isinstance(message, HumanMessage) and "remainingSources" in message.content]
        self.assertEqual(len(recoveries), 1)

    async def test_visual_rejection_is_not_cached_and_another_candidate_can_succeed(self):
        second_image = "https://cdn.example.com/gameplay.jpg"
        page = HTML + f'<img src="{second_image}" alt="Gameplay">'.encode()
        model = model_with(
            tool("search_web", {"query": ORIGINAL + " cover"}),
            tool("read_page", {"resultId": "page-1"}),
            tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
            tool("verify_image", {"candidateId": "image-2", "kind": "cover"}),
            AIMessage(content='{"candidateId":"image-2"}'),
        )
        review = AsyncMock(side_effect=[{"matches": False, "kind": "cover", "reason": "placeholder"},
                                       {"matches": True, "kind": "screenshot", "reason": "matched"}])
        cache = AsyncMock(return_value=cached_image())
        fetch = AsyncMock(side_effect=[PosterResource(SOURCE, page, "text/html"), PosterResource(IMAGE, b"placeholder", "image/png"),
                                      PosterResource(second_image, b"gameplay", "image/png")])
        result = await GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}),
                                      fetch=fetch, cache=cache, review=review).run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(result["posterKind"], "screenshot")
        cache.assert_awaited_once_with(b"gameplay")
        failure = result["posterTrace"][2]
        self.assertEqual(failure["error"], "image_content_mismatch")
        self.assertEqual(failure["imageUrl"], IMAGE)
        self.assertEqual(failure["imageReview"]["reason"], "placeholder")
        self.assertNotIn("imageSha256", failure)
        self.assertEqual(review.call_args.kwargs["item"], ITEM)

    async def test_unavailable_visual_review_cannot_turn_a_download_into_a_success(self):
        model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
                           AIMessage(content='{"candidateId":"image-1"}'))
        cache = AsyncMock()
        result = await GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}),
                                      fetch=AsyncMock(side_effect=[PosterResource(SOURCE, HTML, "text/html"), PosterResource(IMAGE, b"image", "image/png")]),
                                      cache=cache, review=AsyncMock(side_effect=PosterResourceError("image_review_unavailable"))).run(ITEM)
        self.assertEqual(result["posterStatus"], "unavailable")
        cache.assert_not_awaited()


class PlaceholderTests(unittest.TestCase):
    def test_purpose_marked_placeholders_are_filtered_without_game_specific_rules(self):
        paths = ["contribute_ss.webp", "no-screenshot.png", "no_image.jpg", "placeholder.jpg", "missing-cover.png"]
        body = f'<title>{ORIGINAL}</title>' + "".join(f'<img alt="{ORIGINAL}" src="/{path}">' for path in paths)
        body += '<img src="/actual-cover.jpg">'
        page = page_images(SOURCE, body.encode(), ORIGINAL)
        self.assertEqual([candidate["url"] for candidate in page["images"]], ["https://store.example.com/actual-cover.jpg"])


if __name__ == "__main__":
    unittest.main()
