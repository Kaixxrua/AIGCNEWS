from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage, ToolMessage

from backend.app.services.project_catalog.game_poster_agent import GamePosterAgent, _identity_names, page_images
from backend.app.services.project_catalog.game_poster_resources import PosterResource, PosterResourceError
from backend.tests.test_project_web_posters import IMAGE, SOURCE, image_bytes, model_with, tool


def camo(target: str) -> str:
    return "https://camo.githubusercontent.com/digest/" + target.encode().hex()


class PosterCandidateRecallTests(unittest.TestCase):
    def test_readme_badges_cannot_fill_candidate_limit_before_actual_screenshots(self):
        badges = [camo(f"https://img.shields.io/badge/build-{index}-green") for index in range(18)]
        images = [camo("https://cdn.example.org/Scene-One.png"), "https://repository-images.githubusercontent.com/game/artwork.png"]
        body = ('<h1>FreeWorld</h1>' + ''.join(f'<img src="{url}">' for url in badges + images)).encode()
        result = page_images(SOURCE, body, "FreeWorld", project_repo="author/freeworld")
        self.assertTrue(result["matchesGame"])
        self.assertEqual([row["url"] for row in result["images"]], images)

    def test_badge_domain_checks_do_not_discard_unrelated_hosts_or_custom_game_covers(self):
        retained = ["https://notshields.io/artwork.png", "https://shields.io.example.org/scene.png",
                    "https://repository-images.githubusercontent.com/game/cover.png",
                    camo("https://games.example.org/Pixel-Dungeon/cover.png")]
        rejected = ["https://badgen.net/github/stars/author/game", camo("https://badge.fury.io/js/name.png"),
                    camo("https://example.org/build.svg"), "https://opengraph.githubassets.com/token/author/game"]
        body = ('<h1>FreeWorld</h1>' + ''.join(f'<img src="{url}">' for url in rejected + retained)).encode()
        self.assertEqual([row["url"] for row in page_images(SOURCE, body, "FreeWorld")["images"]], retained)

    def test_opaque_camo_is_not_decoded_into_a_guessed_network_request_or_approved_identity(self):
        urls = ["https://camo.githubusercontent.com/hash/not-hex", "https://camo.githubusercontent.com/hash/ff",
                camo("not a URL"), camo("https://[invalid")]
        body = ('<h1>FreeWorld</h1>' + ''.join(f'<img src="{url}">' for url in urls)).encode()
        self.assertEqual([row["url"] for row in page_images(SOURCE, body, "FreeWorld")["images"]], urls)
        self.assertFalse(page_images(SOURCE, body, "Another Game")["matchesGame"])

    def test_github_file_page_is_not_a_linked_original_but_actual_src_and_explicit_raw_survive(self):
        blob = "https://github.com/author/freeworld/blob/main/screenshots/game.png"
        raw = "https://github.com/author/freeworld/raw/main/screenshots/game.png"
        direct = blob + "?raw=true"
        unrelated = "https://github.com.example.org/author/freeworld/blob/main/cover.png"
        body = f'<h1>FreeWorld</h1><a href="{blob}"><img src="{raw}"></a><img src="{direct}"><img src="{unrelated}">'.encode()
        images = page_images(SOURCE, body, "FreeWorld")["images"]
        self.assertEqual([row["url"] for row in images], [raw, direct, unrelated])
        self.assertFalse(any(row.get("linkedOriginal") for row in images))

    def test_region_suffix_does_not_hide_galleries_but_versions_and_sequels_still_matter(self):
        body = f'<h1>FreeWorld 2</h1><figure><img src="{IMAGE}"><figcaption>United States retail box</figcaption></figure>'.encode()
        for region in ("US", "USA", "North America", "Japan", "Europe"):
            original = f"FreeWorld 2 ({region})"
            self.assertTrue(page_images(SOURCE, body, original)["matchesGame"])
            self.assertIn(original, _identity_names(original))
            self.assertFalse(page_images(SOURCE, body.replace(b"FreeWorld 2", b"FreeWorld 3"), original)["matchesGame"])
        self.assertFalse(page_images(SOURCE, body, "FreeWorld 2 (Definitive Edition)")["matchesGame"])
        self.assertFalse(page_images(SOURCE, body + b'<p>2013</p>', "FreeWorld 2 (2014) (US)")["matchesGame"])
        self.assertTrue(page_images(SOURCE, body + b'<p>2014</p>', "FreeWorld 2 (2014) (US)")["matchesGame"])


class IndexedCandidateRecallTests(unittest.IsolatedAsyncioTestCase):
    async def test_regional_search_uses_base_title_and_keeps_full_identity_for_visual_review(self):
        original = "FreeWorld 2 (US)"
        model = model_with(tool("search_web", {"query": "FreeWorld 2 USA cover"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
                           AIMessage(content='{"candidateId":"image-1"}'))
        body = f'<h1>FreeWorld 2</h1><figure><img src="{IMAGE}"><figcaption>United States retail box</figcaption></figure>'.encode()
        review = AsyncMock(return_value={"matches": True, "kind": "cover", "reason": "matched"})
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}),
                                fetch=AsyncMock(side_effect=[PosterResource(SOURCE, body, "text/html"), PosterResource(IMAGE, image_bytes(), "image/png")]),
                                review=review, cache=AsyncMock(return_value={"url": IMAGE}))
        item = {"repo": "author/freeworld", "gameNameOriginal": original}
        result = await agent.run(item)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(review.await_args.kwargs["item"]["gameNameOriginal"], original)
        self.assertIn("United States", review.await_args.kwargs["candidate"]["label"])
        identity = json.loads(model.ainvoke.call_args.args[0][1].content)
        self.assertEqual((identity["searchIdentity"], identity["regionEvidence"]), ("FreeWorld 2", "US"))

    async def test_image_index_cannot_reintroduce_badges_after_source_page_filtering(self):
        badge = camo("https://img.shields.io/badge/build-green")
        model = model_with(tool("search_web", {"query": "FreeWorld screenshot"}),
                           tool("read_page", {"resultId": "page-1"}),
                           AIMessage(content='{"candidateId":""}'), AIMessage(content='{"candidateId":""}'))
        search = AsyncMock(return_value={"results": [
            {"url": SOURCE, "imageUrl": badge},
            {"url": SOURCE, "imageUrl": "https://opengraph.githubassets.com/token/author/game"},
            {"url": SOURCE, "imageUrl": IMAGE},
        ]})
        fetch = AsyncMock(return_value=PosterResource(SOURCE, b'<h1>FreeWorld</h1><p>Project introduction.</p>', "text/html"))
        agent = GamePosterAgent(model, search=search, fetch=fetch)
        await agent.run({"repo": "author/freeworld", "gameNameOriginal": "", "detailsVersion": 1})
        self.assertEqual([row["url"] for row in agent.candidates.values()], [IMAGE])
        self.assertFalse(agent.candidates["image-1"]["inSourcePage"])
        fetch.assert_awaited_once()
        responses = [json.loads(message.content) for message in model.ainvoke.call_args.args[0] if isinstance(message, ToolMessage)]
        self.assertEqual(len(responses[1]["candidates"]), 1)

    async def test_duplicate_verification_in_one_turn_does_not_spend_image_or_model_budget(self):
        model = model_with(tool("search_web", {"query": "FreeWorld screenshot"}),
                           tool("read_page", {"resultId": "page-1"}),
                           AIMessage(content="", tool_calls=[
                               {"name": "verify_image", "args": {"candidateId": "image-1", "kind": kind}, "id": str(i), "type": "tool_call"}
                               for i, kind in enumerate(("cover", "screenshot"))]),
                           tool("verify_image", {"candidateId": "image-2", "kind": "screenshot"}),
                           AIMessage(content='{"candidateId":"image-2"}'))
        second = IMAGE.replace("cover", "scene")
        fetch = AsyncMock(side_effect=[PosterResource(SOURCE, f'<h1>FreeWorld</h1><img src="{IMAGE}"><img src="{second}">'.encode(), "text/html"),
                                      PosterResource(IMAGE, image_bytes(), "image/png"), PosterResource(second, image_bytes(), "image/png")])
        review = AsyncMock(side_effect=[{"matches": False, "kind": "cover", "reason": "uncertain"},
                                       {"matches": True, "kind": "screenshot", "reason": "matched"}])
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}), fetch=fetch,
                                review=review, cache=AsyncMock(return_value={"url": IMAGE, "width": 240, "height": 360}))
        result = await agent.run({"repo": "author/freeworld", "gameNameOriginal": "FreeWorld"})
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(agent.counts["verify_image"], 2)
        self.assertEqual(review.await_count, 2)
        self.assertEqual(fetch.await_count, 3)
        self.assertIn("image_already_tried", [row.get("error") for row in result["posterTrace"]])

    async def test_new_identity_or_source_context_allows_reconsideration_but_another_id_does_not(self):
        agent = GamePosterAgent(model_with())
        candidate = {"url": IMAGE, "sourceUrl": SOURCE, "identityKind": "game", "sourceExcerpt": "FreeWorld"}
        agent.candidates = {"image-1": candidate, "image-2": dict(candidate),
                            "image-3": {**candidate, "identityKind": "project"},
                            "image-4": {**candidate, "sourceExcerpt": "The page provides new version evidence."}}
        for identifier in ("image-1", "image-2", "image-3", "image-4"):
            args = {"candidateId": identifier, "kind": "cover"}
            if identifier == "image-2":
                with self.assertRaisesRegex(PosterResourceError, "image_already_tried"):
                    agent._prepare("verify_image", args, "FreeWorld", {}, "")
            else:
                agent._prepare("verify_image", args, "FreeWorld", {}, "")
        self.assertEqual(agent.counts["verify_image"], 3)
