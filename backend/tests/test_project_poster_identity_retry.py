from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from backend.app.services.project_catalog import game_poster_resources as resources
from backend.app.services.project_catalog.game_poster_resources import PosterResourceError, search_public_web
from backend.tests import test_project_game_posters as fixtures


class SearchDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_reports_bounded_codes_without_provider_secrets(self):
        payload = {"unavailable": True, "results": [], "attempts": [
            {"engine": "google", "status": "unavailable", "httpStatus": 403, "errorType": "DDGSException", "message": "PRIVATE SECRET"},
            {"engine": "yahoo", "status": "empty", "parser": "yahoo_headings", "elapsedMs": 1250, "resultCount": 0, "response": "PRIVATE SECRET"},
        ]}
        with patch.object(resources, "_search_worker", AsyncMock(return_value=json.dumps(payload).encode())):
            with self.assertRaises(PosterResourceError) as caught:
                await search_public_web("Example Game cover")
        self.assertEqual(str(caught.exception), "search_unavailable")
        self.assertEqual(len(caught.exception.attempts), 2)
        self.assertEqual(caught.exception.attempts[0]["httpStatus"], 403)
        self.assertNotIn("PRIVATE", json.dumps(caught.exception.attempts))
        self.assertEqual(resources._search_attempts([{"engine": [], "status": {}}]), [])


@unittest.skipUnless(os.environ.get("PORTSHELF_TEST_REDIS_URL"), "set isolated PORTSHELF_TEST_REDIS_URL")
class IdentityRetryTests(unittest.IsolatedAsyncioTestCase):
    cache_key = fixtures.GamePosterRedisTests.cache_key
    lock_key = fixtures.GamePosterRedisTests.lock_key
    daily_key = fixtures.GamePosterRedisTests.daily_key
    seed = fixtures.GamePosterRedisTests.seed
    read = fixtures.GamePosterRedisTests.read
    asyncTearDown = fixtures.GamePosterRedisTests.asyncTearDown

    async def asyncSetUp(self):
        await fixtures.GamePosterRedisTests.asyncSetUp(self)
        self.research = AsyncMock(return_value={"posterStatus": "unavailable", "posterTrace": []})
        self.service.research_poster = self.research
        self.service.poster_exists = lambda _: True

    async def request(self, *, refresh=False):
        return await self.service.request(fixtures.REPO, redis=self.redis, authorization=self.authorization,
                                          operations=self.operations, game_details=True, refresh_poster=refresh)

    async def test_explicit_refresh_rechecks_old_empty_identity_once_and_preserves_description_and_image(self):
        await self.seed(**fixtures.POSTER, gameNameOriginal="", gameNameZh="", identityEvidenceVersion=0,
                        posterSearchVersion=1, posterRetryAt=0, posterStatus="ready")
        await self.read()
        self.fetch.assert_not_awaited()
        self.assertEqual((await self.request())["status"], "ready")
        self.assertEqual(self.operations.jobs, [])
        await asyncio.gather(self.request(refresh=True), self.request(refresh=True))
        self.assertEqual(len(self.operations.jobs), 1)
        self.assertEqual(await self.redis.get(self.daily_key()), "1")
        await self.operations.run()
        result = await self.read()
        self.assertEqual(result["gameNameOriginal"], fixtures.ORIGINAL)
        self.assertEqual(result["descriptionZh"], fixtures.ZH)
        self.assertEqual(result["posterUrl"], fixtures.IMAGE)
        self.assertEqual(result["identityEvidenceVersion"], 2)
        self.assertEqual(self.research.await_args.args[0]["gameNameOriginal"], fixtures.ORIGINAL)
        self.now += 301
        await self.request(refresh=True)
        await self.operations.run()
        self.describe_game.assert_awaited_once()
        self.fetch.assert_awaited_once()

    async def test_multi_game_unknown_identity_is_not_regenerated_on_every_poster_retry(self):
        await self.seed(gameNameOriginal="", gameNameZh="", identityEvidenceVersion=0,
                        posterSearchVersion=1, posterRetryAt=0, posterStatus="unavailable")
        self.describe_game.return_value = {**fixtures.GAME_RESULT, "game_identity": "unknown", "game_name_original": "", "game_name_zh": ""}
        await self.request(refresh=True)
        await self.operations.run()
        result = await self.read()
        self.assertEqual(result["gameNameOriginal"], "")
        self.assertEqual(result["identityEvidenceVersion"], 2)
        self.now += 301
        await self.request(refresh=True)
        await self.operations.run()
        self.describe_game.assert_awaited_once()
        self.assertEqual(self.research.await_count, 2)

    async def test_identity_repair_failure_keeps_existing_data_and_continues_project_search(self):
        await self.seed(**fixtures.POSTER, gameNameOriginal="", gameNameZh="", identityEvidenceVersion=0,
                        posterSearchVersion=1, posterRetryAt=0, posterStatus="ready")
        self.fetch.side_effect = RuntimeError("PRIVATE provider credential")
        await self.request(refresh=True)
        await self.operations.run()
        result = await self.read()
        self.assertEqual(result["descriptionZh"], fixtures.ZH)
        self.assertEqual(result["posterUrl"], fixtures.IMAGE)
        self.assertEqual(result["identityEvidenceVersion"], 0)
        self.research.assert_awaited_once()
        self.assertNotIn("PRIVATE", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
