from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage

from backend.app.services.project_catalog.game_poster_agent import GamePosterAgent
from backend.app.services.project_catalog.game_poster_resources import PosterResource
from backend.tests.test_project_poster_coverage import cached_image
from backend.tests.test_project_web_posters import HTML, IMAGE, ITEM, ORIGINAL, SOURCE, model_with, tool


class PosterPreviewTraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_frame_evidence_survives_acceptance_and_rejection_without_arbitrary_metadata(self):
        for matches in (True, False):
            with self.subTest(matches=matches):
                model = model_with(tool("search_web", {"query": ORIGINAL + " gameplay"}),
                                   tool("read_page", {"resultId": "page-1"}),
                                   tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
                                   AIMessage(content='{"candidateId":"image-1"}' if matches else '{"candidateId":""}'))
                preview = {"type": "gif_frame", "frameIndex": 2, "framesValidated": 3, "partial": True,
                           "sourcePrefixSha256": "a" * 64, "downloadedBytes": 1000,
                           "sourceBytes": "private-provider-message", "width": True, "height": -1,
                           "frameEnd": 2**65, "untrustedText": "private-provider-message"}
                resource = SimpleNamespace(url=IMAGE, body=b"image", content_type="image/jpeg", preview=preview)
                fetch = AsyncMock(side_effect=[PosterResource(SOURCE, HTML, "text/html"), resource])
                cache = AsyncMock(return_value=cached_image())
                review = AsyncMock(return_value={"matches": matches, "kind": "screenshot", "reason": "matched" if matches else "wrong_game"})
                agent = GamePosterAgent(model, fetch=fetch, cache=cache, review=review,
                                        search=AsyncMock(return_value={"results": [{"url": SOURCE}]}))
                result = await agent.run(ITEM)
                record = next(row for row in result["posterTrace"] if row.get("tool") == "verify_image")
                self.assertEqual(record["imagePreview"], {
                    "type": "gif_frame", "frameIndex": 2, "framesValidated": 3, "partial": True,
                    "sourcePrefixSha256": "a" * 64, "downloadedBytes": 1000,
                })
                self.assertEqual(record["status"], "succeeded" if matches else "failed")
                self.assertEqual(cache.await_count, int(matches))
                review.assert_awaited_once()
