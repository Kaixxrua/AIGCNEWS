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
        responses = [json.loads(message.content) for message in model.ainvoke.call_args.args[0] if isinstance(message, ToolMessage)]
        self.assertEqual(responses[2]["imageReview"], {"matches": False, "kind": "cover", "reason": "placeholder"})

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

class BoundedRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_read_is_not_fetched_or_charged_and_budget_is_visible(self):
        model = model_with(
            tool("search_web", {"query": ORIGINAL + " cover"}),
            AIMessage(content="", tool_calls=[
                {"name": "read_page", "args": {"resultId": "page-1"}, "id": "read", "type": "tool_call"},
                {"name": "read_page", "args": {"resultId": "page-1"}, "id": "repeat", "type": "tool_call"},
            ]),
            tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
            AIMessage(content='{"candidateId":"image-1"}'),
        )
        fetch = AsyncMock(side_effect=[PosterResource(SOURCE, HTML, "text/html"), PosterResource(IMAGE, b"image", "image/png")])
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}),
                                fetch=fetch, cache=AsyncMock(return_value=cached_image()))
        result = await agent.run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(agent.counts["read_page"], 1)
        self.assertEqual(result["posterTrace"][2]["error"], "page_already_read")
        messages = [json.loads(message.content) for message in model.ainvoke.call_args.args[0] if isinstance(message, ToolMessage)]
        self.assertEqual(messages[2]["remainingBudget"]["read_page"], 5)

    async def test_thumbnail_failure_follows_evidenced_detail_page_to_large_image(self):
        gallery = SOURCE + "/covers"
        thumb = IMAGE.replace("cover", "thumb")
        listing = f'<h1>{ORIGINAL}</h1><a href="{gallery}"><img src="{thumb}"></a>'.encode()
        model = model_with(
            tool("search_web", {"query": ORIGINAL + " cover"}),
            tool("read_page", {"resultId": "page-1"}),
            tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
            tool("read_page", {"resultId": "page-2"}),
            tool("verify_image", {"candidateId": "image-2", "kind": "cover"}),
            AIMessage(content='{"candidateId":"image-2"}'),
        )
        fetch = AsyncMock(side_effect=[PosterResource(SOURCE, listing, "text/html"), PosterResource(thumb, b"small", "image/png"),
                                      PosterResource(gallery, HTML, "text/html"), PosterResource(IMAGE, b"large", "image/png")])
        review = AsyncMock(side_effect=[PosterResourceError("invalid_image"), {"matches": True, "kind": "cover", "reason": "matched"}])
        cache = AsyncMock(return_value=cached_image())
        result = await GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}),
                                      fetch=fetch, review=review, cache=cache).run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(result["posterSourceUrl"], gallery)
        cache.assert_awaited_once_with(b"large")
        failure = [json.loads(message.content) for message in model.ainvoke.call_args.args[0] if isinstance(message, ToolMessage)][2]
        self.assertEqual(failure["error"], "invalid_image")
        self.assertIn("详情", failure["nextStep"])
        self.assertEqual(failure["unreadSources"][0]["url"], gallery)

    async def test_independent_project_can_find_own_art_without_changing_original_identity(self):
        item = {**ITEM, "repo": "example/free-world", "gameNameOriginal": "Commercial Classic", "detailsVersion": 1,
                "descriptionZh": "基于原作引擎、完全使用自由素材的独立游戏。"}
        source = "https://free-world.example.org/"
        body = f'<h1>Free World</h1><p>An independent game</p><a href="https://github.com/example/free-world">Source</a><img src="{IMAGE}">'.encode()
        model = model_with(tool("search_web", {"query": "free-world screenshots"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
                           AIMessage(content='{"candidateId":"image-1"}'))
        review = AsyncMock(return_value={"matches": True, "kind": "screenshot", "reason": "matched"})
        result = await GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": source}]}),
                                      fetch=AsyncMock(side_effect=[PosterResource(source, body, "text/html"), PosterResource(IMAGE, b"own game", "image/png")]),
                                      review=review, cache=AsyncMock(return_value=cached_image())).run(item)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(result["posterTrace"][0]["identityKind"], "project")
        self.assertEqual(review.call_args.kwargs["candidate"]["identityKind"], "project")
        self.assertEqual(item["gameNameOriginal"], "Commercial Classic")
        self.assertNotIn("gameNameOriginal", result)

    async def test_unverified_project_name_does_not_expand_allowed_identity(self):
        model = model_with(tool("search_web", {"query": "free-world screenshots"}), AIMessage(content='{"candidateId":""}'))
        search = AsyncMock()
        result = await GamePosterAgent(model, search=search).run({**ITEM, "repo": "example/free-world"})
        search.assert_not_awaited()
        self.assertEqual(result["posterTrace"][0]["error"], "query_must_include_game")

    async def test_project_fallback_reparses_same_evidenced_page_without_second_download(self):
        item = {**ITEM, "repo": "example/free-world", "gameNameOriginal": "Commercial Classic", "detailsVersion": 1}
        source = "https://free-world.example.org/"
        body = f'<h1>Free World</h1><a href="https://github.com/example/free-world">Project source</a><img src="{IMAGE}">'.encode()
        model = model_with(tool("search_web", {"query": "Commercial Classic cover"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("search_web", {"query": "free-world screenshots"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
                           AIMessage(content='{"candidateId":"image-1"}'))
        fetch = AsyncMock(side_effect=[PosterResource(source, body, "text/html"), PosterResource(IMAGE, b"own game", "image/png")])
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": source}]}),
                                fetch=fetch, cache=AsyncMock(return_value=cached_image()))
        result = await agent.run(item)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(agent.counts["read_page"], 1)
        self.assertTrue(result["posterTrace"][3]["reusedPage"])
        self.assertEqual(result["posterTrace"][0]["results"][0]["identityKind"], "game")
        self.assertEqual(result["posterTrace"][2]["results"][0]["identityKind"], "project")
        self.assertEqual(result["posterTrace"][1]["candidateIds"], [])
        self.assertEqual(result["posterTrace"][3]["candidateIds"], ["image-1"])
        self.assertEqual(result["posterTrace"][1]["pageSha256"], result["posterTrace"][3]["pageSha256"])

    async def test_project_identity_reaches_existing_gallery_link_and_reuses_its_download(self):
        item = {**ITEM, "repo": "example/free-world", "gameNameOriginal": "Commercial Classic", "detailsVersion": 1}
        source, gallery = "https://free-world.example.org/game", "https://free-world.example.org/game/covers"
        parent = f'<h1>Free World</h1><p>Free content based on Commercial Classic.</p><a href="https://github.com/example/free-world">Source</a><a href="{gallery}">Covers</a>'.encode()
        body = f'<h1>Free World</h1><a href="https://github.com/example/free-world">Project source</a><img src="{IMAGE}">'.encode()
        model = model_with(tool("search_web", {"query": "Commercial Classic cover"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("read_page", {"resultId": "page-2"}),
                           tool("search_web", {"query": "free-world screenshots"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("read_page", {"resultId": "page-2"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
                           AIMessage(content='{"candidateId":"image-1"}'))
        fetch = AsyncMock(side_effect=[PosterResource(source, parent, "text/html"), PosterResource(gallery, body, "text/html"),
                                      PosterResource(IMAGE, b"own game", "image/png")])
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": source}]}),
                                fetch=fetch, cache=AsyncMock(return_value=cached_image()))
        result = await agent.run(item)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(fetch.await_count, 3)
        self.assertEqual(agent.counts["read_page"], 2)
        self.assertEqual(agent.results["page-2"]["parentResultId"], "page-1")
        self.assertEqual(result["posterTrace"][1]["linkedResults"][0]["identityKind"], "game")
        self.assertEqual(result["posterTrace"][4]["linkedResults"][0]["identityKind"], "project")
        self.assertTrue(result["posterTrace"][5]["reusedPage"])

    async def test_wrong_original_cover_feedback_directs_recovery_to_project_identity(self):
        item = {**ITEM, "repo": "example/free-world", "gameNameOriginal": "Commercial Classic", "detailsVersion": 1}
        project_page = f'<h1>Free World</h1><a href="https://github.com/example/free-world">Source</a><img src="{IMAGE}">'.encode()
        original_page = f'<h1>Commercial Classic</h1><img src="{IMAGE}">'.encode()
        responses = [tool("search_web", {"query": "Commercial Classic cover"}), tool("read_page", {"resultId": "page-1"}),
                     tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
                     tool("search_web", {"query": "free-world screenshots"}), tool("read_page", {"resultId": "page-2"}),
                     tool("verify_image", {"candidateId": "image-2", "kind": "screenshot"}), AIMessage(content='{"candidateId":"image-2"}')]
        model = model_with(*responses)
        fetch = AsyncMock(side_effect=[PosterResource(SOURCE, original_page, "text/html"), PosterResource(IMAGE, b"wrong", "image/png"),
                                      PosterResource(SOURCE + "project", project_page, "text/html"), PosterResource(IMAGE, b"own game", "image/png")])
        review = AsyncMock(side_effect=[{"matches": False, "kind": "cover", "reason": "wrong_game"},
                                       {"matches": True, "kind": "screenshot", "reason": "matched"}])
        search = AsyncMock(side_effect=[{"results": [{"url": SOURCE}]}, {"results": [{"url": SOURCE + "project"}]}])
        result = await GamePosterAgent(model, search=search, fetch=fetch, review=review, cache=AsyncMock(return_value=cached_image())).run(item)
        self.assertEqual(result["posterStatus"], "ready")
        messages = [json.loads(message.content) for message in model.ainvoke.call_args.args[0] if isinstance(message, ToolMessage)]
        self.assertEqual(messages[2]["imageReview"]["reason"], "wrong_game")
        self.assertIn("projectSearchIdentity", messages[2]["nextStep"])
        self.assertEqual(messages[2]["remainingBudget"]["verify_image"], 2)
