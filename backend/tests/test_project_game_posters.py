from __future__ import annotations

import asyncio
import json
import os
import secrets
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

import httpx

from backend.app.services.api_access import quota
from backend.app.services.auth.rate_limit import RateLimitExceededError
from backend.app.services.mcp.inbound.context import McpAuthorizationContext
from backend.app.services.project_catalog import descriptions_service as service_module
from backend.app.services.project_catalog.descriptions_service import (
    DescriptionBusy,
    DescriptionsUnavailable,
    ProjectDescriptionsService,
)
from backend.app.services.project_catalog.game_details import image_candidates
from backend.app.services.project_catalog.game_posters import (
    MAX_POSTER_RESPONSE_BYTES,
    POSTER_MISSING_SECONDS,
    POSTER_UNAVAILABLE_SECONDS,
    PosterUnavailable,
    exact_game_titles,
    fetch_wikipedia_poster,
    normalize_wikimedia_image,
    wikipedia_cover,
)
from backend.tests.test_project_descriptions import USER, QueuedOperations, client

REPO = "valentderah/totk-pc-recomp"
ORIGINAL = "The Legend of Zelda: Tears of the Kingdom"
ZH = "将《塞尔达传说：王国之泪》静态重编译为可在电脑运行的原生游戏。"
IMAGE = "https://upload.wikimedia.org/wikipedia/en/f/fb/The_Legend_of_Zelda_Tears_of_the_Kingdom_cover.jpg"
SOURCE = "https://en.wikipedia.org/wiki/The_Legend_of_Zelda:_Tears_of_the_Kingdom"
POSTER = {"posterUrl": IMAGE, "posterSourceUrl": SOURCE, "posterKind": "cover"}
GAME_RESULT = {
    "description_zh": ZH, "game_identity": "single_game",
    "game_name_zh": "塞尔达传说：王国之泪", "game_name_original": ORIGINAL,
    "poster_candidate_id": "", "poster_kind": "",
}


def ready_without_poster():
    return {
        "repo": REPO, "status": "ready", "descriptionZh": ZH, "source": "aigcnews",
        "gameNameZh": "塞尔达传说：王国之泪", "gameNameOriginal": ORIGINAL,
        "posterUrl": "", "posterSourceUrl": "", "posterKind": "", "detailsVersion": 1,
    }


def page():
    return {
        "pageid": 60768452, "ns": 0, "title": ORIGINAL, "fullurl": SOURCE,
        "pageimage": "The_Legend_of_Zelda_Tears_of_the_Kingdom_cover.jpg",
        "thumbnail": {
            "source": IMAGE + "?utm_source=en.wikipedia.org&utm_campaign=api&utm_content=thumbnail_unscaled",
            "width": 268, "height": 372,
        },
        "pageprops": {}, "categories": [{"title": "Category:2023 video games"}],
    }


class WikipediaCoverSafetyTests(unittest.TestCase):
    def test_verified_game_page_is_cover_with_clean_image_and_article_source(self):
        self.assertEqual(wikipedia_cover(page(), ORIGINAL), POSTER)
        thumbnail = deepcopy(page())
        filename = thumbnail["pageimage"]
        thumbnail["thumbnail"]["source"] = f"https://upload.wikimedia.org/wikipedia/en/thumb/f/fb/{filename}/600px-{filename}"
        self.assertEqual(wikipedia_cover(thumbnail, ORIGINAL)["posterUrl"], thumbnail["thumbnail"]["source"])
        commons = IMAGE.replace("/en/", "/commons/")
        self.assertEqual(normalize_wikimedia_image(commons), commons)

    def test_titles_are_exact_with_only_explicit_video_game_suffix(self):
        alternate = {**page(), "title": ORIGINAL + " (video game)", "fullurl": SOURCE + "_(video_game)", "categories": []}
        self.assertEqual(wikipedia_cover(alternate, ORIGINAL)["posterSourceUrl"], SOURCE + "_(video_game)")
        self.assertIsNotNone(wikipedia_cover(page(), ORIGINAL.lower().replace(" ", "_")))
        quoted = {**page(), "title": "The Legend of Zelda: Link's Awakening", "fullurl": "https://en.wikipedia.org/wiki/The_Legend_of_Zelda:_Link%27s_Awakening"}
        self.assertIsNotNone(wikipedia_cover(quoted, "The Legend of Zelda: Link’s Awakening"))
        for wrong in ["The Legend of Zelda", "The Legend of Zelda: Breath of the Wild", ORIGINAL + " 2", ORIGINAL + " (2023 video game)"]:
            with self.subTest(wrong=wrong):
                candidate = {**page(), "title": wrong, "fullurl": "https://en.wikipedia.org/wiki/" + quote(wrong.replace(" ", "_"))}
                self.assertIsNone(wikipedia_cover(candidate, ORIGINAL))
        self.assertEqual(exact_game_titles("Doom (video game)"), ["Doom (video game)"])
        self.assertEqual(exact_game_titles('A “Quoted” Game'), ['A "Quoted" Game', 'A "Quoted" Game (video game)'])
        for unsafe in [None, "", "ab", "x" * 161, "Game|Another game", "Game\n", "Game#part", "https://example.com/game"]:
            self.assertEqual(exact_game_titles(unsafe), [])

    def test_namesake_novel_disambiguation_namespaces_and_wrong_source_are_rejected(self):
        novel = {**page(), "title": "Dune", "fullurl": "https://en.wikipedia.org/wiki/Dune", "categories": [{"title": "Category:1965 novels"}, {"title": "Category:Films based on video games"}]}
        self.assertIsNone(wikipedia_cover(novel, "Dune"))
        for change in [
            {"ns": 6}, {"ns": False}, {"missing": True}, {"pageid": 0}, {"pageid": True},
            {"pageprops": {"disambiguation": ""}}, {"pageprops": []}, {"categories": []},
            {"fullurl": SOURCE.replace("en.wikipedia.org", "example.org")},
            {"fullurl": SOURCE.replace("en.wikipedia.org", "en.wikipedia.org:443")},
            {"fullurl": SOURCE.replace("https://", "https://user@")},
            {"fullurl": SOURCE + "?redirect=1"}, {"fullurl": SOURCE + "#Cover"},
            {"fullurl": SOURCE + "_2"}, {"fullurl": None},
        ]:
            with self.subTest(change=change):
                self.assertIsNone(wikipedia_cover({**page(), **change}, ORIGINAL))

    def test_images_reject_svg_decorations_and_wrong_file_evidence(self):
        for name in ["Game_logo.png", "Game_badge.jpg", "Game_icon.webp", "Game_cover.svg", "Game_cover.svg.png", "Game_cover.gif", "Game_tracker.png"]:
            candidate = page()
            candidate["pageimage"] = name
            candidate["thumbnail"]["source"] = "https://upload.wikimedia.org/wikipedia/en/f/fb/" + name
            self.assertIsNone(wikipedia_cover(candidate, ORIGINAL), name)
        for changes in [
            {"width": 1}, {"height": 179}, {"height": 2001}, {"width": True},
            {"source": IMAGE.replace("cover.jpg", "wrong-cover.jpg")},
        ]:
            candidate = page()
            candidate["thumbnail"].update(changes)
            self.assertIsNone(wikipedia_cover(candidate, ORIGINAL))

    def test_fixed_image_host_paths_and_only_known_tracking_parameters(self):
        for unsafe in [
            IMAGE.replace("https:", "http:"), IMAGE.replace("upload.wikimedia.org", "upload.wikimedia.org.evil.test"),
            IMAGE.replace("upload.wikimedia.org", "127.0.0.1"), IMAGE.replace("https://", "https://user:pass@"),
            IMAGE.replace("upload.wikimedia.org", "upload.wikimedia.org:443"), IMAGE + "#part",
            IMAGE.replace("/wikipedia/en/", "/private/en/"), IMAGE.replace("/wikipedia/en/", "/wikipedia/fr/"),
            IMAGE.replace("/f/fb/", "/f/fb/../"), IMAGE.replace("/f/fb/", "/f/fb/%2e%2e/"),
            IMAGE.replace("/f/fb/", "/f/fb/%252e%252e/"), IMAGE.replace("/f/fb/", "/f/fb//"),
            IMAGE.replace("/f/fb/", "/f/fb/extra/"), IMAGE + "/other.jpg",
            IMAGE.replace("/f/fb/", "/f/fb/\\"), IMAGE.replace("cover.jpg", "cover.svg.png"),
            IMAGE + "?url=https://evil.test", IMAGE + "?utm_source=x&utm_source=y",
            IMAGE + "?utm_source=", IMAGE + "?utm_source=a%2Fb", IMAGE + "?utm_source",
        ]:
            with self.subTest(unsafe=unsafe):
                self.assertEqual(normalize_wikimedia_image(unsafe), "")


class WikipediaRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_is_one_bounded_anonymous_exact_title_api_lookup(self):
        seen = []

        def handle(request):
            seen.append(request)
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.host, "en.wikipedia.org")
            self.assertEqual(request.url.path, "/w/api.php")
            self.assertEqual(request.url.params["titles"], ORIGINAL + "|" + ORIGINAL + " (video game)")
            self.assertEqual(request.url.params["cllimit"], "50")
            self.assertNotIn("search", request.url.params)
            self.assertNotIn("authorization", request.headers)
            self.assertNotIn("cookie", request.headers)
            return httpx.Response(200, json={"query": {"pages": [page()]}, "continue": {"clcontinue": "ignored"}})

        result = await fetch_wikipedia_poster(ORIGINAL, transport=httpx.MockTransport(handle))
        self.assertEqual(result, POSTER)
        self.assertEqual(len(seen), 1)

    async def test_redirect_overflow_upstream_errors_invalid_json_fail_closed(self):
        for response in [
            httpx.Response(302, headers={"Location": "https://127.0.0.1/private"}),
            httpx.Response(429), httpx.Response(503),
            httpx.Response(200, content=b"x" * (MAX_POSTER_RESPONSE_BYTES + 1)),
            httpx.Response(200, content=b"invalid-json"),
            httpx.Response(200, json={"error": {"code": "denied"}}),
            httpx.Response(200, json={"query": {"pages": [page()] * 5}}),
            httpx.Response(200, json={"query": []}),
        ]:
            seen = []

            def handle(request):
                seen.append(request)
                return response

            with self.assertRaises(PosterUnavailable):
                await fetch_wikipedia_poster(ORIGINAL, transport=httpx.MockTransport(handle))
            self.assertEqual(len(seen), 1)

    async def test_missing_or_unrelated_pages_are_missing_and_bad_title_never_requests(self):
        seen = []

        def handle(request):
            seen.append(request)
            return httpx.Response(200, json={"query": {"pages": [{"ns": 0, "title": ORIGINAL, "missing": True}, {**page(), "title": ORIGINAL + " 2"}]}})

        self.assertIsNone(await fetch_wikipedia_poster(ORIGINAL, transport=httpx.MockTransport(handle)))
        self.assertEqual(len(seen), 1)
        self.assertIsNone(await fetch_wikipedia_poster("Injected|Title", transport=httpx.MockTransport(handle)))
        self.assertEqual(len(seen), 1)


class PosterRouteTests(unittest.TestCase):
    def test_optional_poster_states_are_public_but_cache_internals_are_not(self):
        browser, service = client()
        response = browser.get("/api/v1/projects/descriptions", params={"repos": REPO})
        self.assertNotIn("posterStatus", response.json()["items"][0])
        for status, retry in [("missing", POSTER_MISSING_SECONDS), ("unavailable", POSTER_UNAVAILABLE_SECONDS), ("ready", 0)]:
            result = {**ready_without_poster(), "posterStatus": status, "posterRetryAfter": retry, "posterRetryAt": 12345, "token": "internal-test-lease"}
            service.read.return_value = [result]
            service.request.return_value = {**result, "status": "pending"}
            for response in [
                browser.get("/api/v1/projects/descriptions", params={"repos": REPO, "gameDetails": "true"}),
                browser.post("/api/v1/projects/descriptions", json={"repo": REPO, "gameDetails": True}),
            ]:
                payload = response.json()["items"][0]
                self.assertEqual(payload["posterStatus"], status)
                self.assertEqual(payload["posterRetryAfter"], retry)
                self.assertEqual(payload["descriptionZh"], ZH)
                self.assertNotIn("posterRetryAt", payload)
                self.assertNotIn("token", payload)


@unittest.skipUnless(os.environ.get("PORTSHELF_TEST_REDIS_URL"), "set isolated PORTSHELF_TEST_REDIS_URL for real Redis contracts")
class GamePosterRedisTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from redis.asyncio import Redis

        self.redis = Redis.from_url(os.environ["PORTSHELF_TEST_REDIS_URL"], decode_responses=True)
        await self.redis.ping()
        self.prefix = "projects:game-poster:test:" + secrets.token_hex(8) + ":"
        self.prefix_patch = patch.object(service_module, "PREFIX", self.prefix)
        self.prefix_patch.start()
        self.user_id = secrets.randbelow(1_000_000_000) + 1_000_000_000
        self.authorization = McpAuthorizationContext({**USER, "user_id": self.user_id})
        self.repo = SimpleNamespace(lookup=lambda names: {})
        self.fetch = AsyncMock(return_value={
            "full_name": REPO, "description": f"Static recompilation of {ORIGINAL}", "default_branch": "main",
            "readme_path": "README.md", "readme_text": f"# Game\n{ORIGINAL}", "image_candidates": [],
        })
        self.describe = AsyncMock(return_value=ZH)
        self.describe_game = AsyncMock(return_value=dict(GAME_RESULT))
        self.fetch_poster = AsyncMock(return_value=dict(POSTER))
        self.now = 1794000000.0
        self.service = ProjectDescriptionsService(
            self.describe, describe_game=self.describe_game, repository=self.repo, fetch=self.fetch,
            fetch_poster=self.fetch_poster, clock=lambda: self.now,
        )
        self.operations = QueuedOperations()

    async def asyncTearDown(self):
        keys = []
        for pattern in [self.prefix + "*", f"ratelimit:*:user:{self.user_id}", f"ratelimit:*:ip:{self.user_id}"]:
            keys.extend([key async for key in self.redis.scan_iter(match=pattern)])
        if keys:
            await self.redis.delete(*keys)
        try:
            await self.redis.close()
        finally:
            self.prefix_patch.stop()

    @property
    def cache_key(self):
        return self.prefix + "cache:game-v1:" + REPO

    @property
    def lock_key(self):
        return self.prefix + "lock:game-v1:" + REPO

    def daily_key(self):
        return f"ratelimit:{quota.API_QUOTA_DAILY_BUCKET}:user:{self.user_id}"

    async def request(self, repo=REPO, *, game_details=True):
        return await self.service.request(repo, redis=self.redis, authorization=self.authorization, operations=self.operations, game_details=game_details)

    async def read(self):
        return (await self.service.read([REPO], redis=self.redis, client_ip=str(self.user_id), game_details=True))[0]

    async def seed(self, **changes):
        await self.redis.set(self.cache_key, json.dumps({**ready_without_poster(), **changes}), ex=service_module.READY_TTL)

    def assert_verified_text(self, result):
        self.assertEqual(result["descriptionZh"], ZH)
        self.assertEqual(result["gameNameOriginal"], ORIGINAL)
        self.assertEqual(result["gameNameZh"], "塞尔达传说：王国之泪")
        self.assertEqual(result["detailsVersion"], 1)

    async def test_old_empty_v1_poster_upgrades_once_without_quota_or_model_even_at_quota_limit(self):
        await self.seed()
        await self.redis.set(self.daily_key(), quota.API_MEMBER_DAILY_SEARCH_QUOTA, ex=60)
        before = await self.read()
        self.assertEqual(before["posterRetryAfter"], 0)
        self.fetch_poster.assert_not_awaited()
        first, second = await asyncio.gather(self.request(), self.request())
        for pending in [first, second, await self.read()]:
            self.assertEqual(pending["status"], "pending")
            self.assert_verified_text(pending)
        self.assertEqual(len(self.operations.jobs), 1)
        self.fetch_poster.assert_not_awaited()
        await self.operations.run()
        ready = await self.read()
        self.assert_verified_text(ready)
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["posterStatus"], "ready")
        self.assertEqual(ready["posterRetryAfter"], 0)
        self.assertEqual(ready["posterUrl"], IMAGE)
        self.assertEqual((await self.request())["posterUrl"], IMAGE)
        self.assertEqual(await self.redis.get(self.daily_key()), str(quota.API_MEMBER_DAILY_SEARCH_QUOTA))
        self.fetch_poster.assert_awaited_once_with(ORIGINAL)
        self.fetch.assert_not_awaited()
        self.describe.assert_not_awaited()
        self.describe_game.assert_not_awaited()
        self.assertFalse(await self.redis.exists(self.lock_key))

    async def test_missing_and_unavailable_keep_text_and_cool_down_without_repeating_generation(self):
        for outcome, status, cooldown in [
            (None, "missing", POSTER_MISSING_SECONDS),
            (RuntimeError("SECRET transport credentials"), "unavailable", POSTER_UNAVAILABLE_SECONDS),
        ]:
            with self.subTest(status=status):
                await self.seed()
                self.fetch_poster.reset_mock(side_effect=True, return_value=True)
                if isinstance(outcome, Exception):
                    self.fetch_poster.side_effect = outcome
                else:
                    self.fetch_poster.return_value = outcome
                await self.request()
                await self.operations.run()
                result = await self.read()
                self.assert_verified_text(result)
                self.assertEqual(result["status"], "ready")
                self.assertEqual(result["posterStatus"], status)
                self.assertEqual(result["posterRetryAfter"], cooldown)
                self.assertNotIn("SECRET", json.dumps(result))
                self.now += 17
                self.assertEqual((await self.request())["posterRetryAfter"], cooldown - 17)
                self.assertEqual(self.operations.jobs, [])
                self.fetch_poster.assert_awaited_once()
                self.now += cooldown
                self.assertEqual((await self.request())["status"], "pending")
                await self.operations.run()
                self.assertEqual(self.fetch_poster.await_count, 2)
        self.assertIsNone(await self.redis.get(self.daily_key()))
        self.describe_game.assert_not_awaited()
        self.fetch.assert_not_awaited()

    async def test_new_generation_falls_back_after_no_or_invalid_selected_readme_image(self):
        for candidate_id in ["", "invented-image-900", "image-1"]:
            with self.subTest(candidate_id=candidate_id):
                await self.redis.delete(self.cache_key)
                self.describe_game.return_value = {**GAME_RESULT, "poster_candidate_id": candidate_id, "poster_kind": "cover"}
                self.fetch.return_value["image_candidates"] = [{"id": "image-1", "url": "http://127.0.0.1/private.jpg", "sourceUrl": "https://evil.test"}]
                await self.request()
                await self.operations.run()
                result = await self.read()
                self.assertEqual(result["posterUrl"], IMAGE)
                self.assert_verified_text(result)
        self.assertEqual(self.describe_game.await_count, 3)
        self.assertEqual(self.fetch_poster.await_count, 3)
        self.assertEqual(await self.redis.get(self.daily_key()), "3")

    async def test_new_generation_poster_failure_then_poster_only_repair_never_regenerates_text(self):
        self.fetch_poster.side_effect = PosterUnavailable("temporarily unavailable")
        await self.request()
        await self.operations.run()
        self.assert_verified_text(await self.read())
        self.assertEqual((await self.read())["posterStatus"], "unavailable")
        self.now += POSTER_UNAVAILABLE_SECONDS + 1
        self.fetch_poster.side_effect = None
        await self.request()
        await self.operations.run()
        self.assertEqual((await self.read())["posterStatus"], "ready")
        self.describe_game.assert_awaited_once()
        self.fetch.assert_awaited_once()
        self.assertEqual(await self.redis.get(self.daily_key()), "1")

    async def test_valid_readme_image_or_unknown_game_identity_never_calls_fallback(self):
        readme = f"# Game\n{ORIGINAL}\n![Game screenshot](docs/scene.jpg)"
        self.fetch.return_value.update(readme_text=readme, image_candidates=image_candidates(REPO, "main", "README.md", readme))
        self.describe_game.return_value = {**GAME_RESULT, "poster_candidate_id": "image-1", "poster_kind": "screenshot"}
        await self.request()
        await self.operations.run()
        self.assertEqual((await self.read())["posterKind"], "screenshot")
        await self.redis.delete(self.cache_key)
        self.describe_game.return_value = {**GAME_RESULT, "game_identity": "unknown"}
        await self.request()
        await self.operations.run()
        self.now += POSTER_MISSING_SECONDS + 1
        self.assertEqual((await self.request())["status"], "ready")
        self.fetch_poster.assert_not_awaited()
        self.assertEqual(self.describe_game.await_count, 2)

    async def test_poster_jobs_share_slots_post_rate_limit_and_fenced_finish(self):
        await self.seed()
        for index in range(4):
            await self.request(f"acme/game{index}", game_details=False)
        with self.assertRaises(DescriptionBusy):
            await self.request()
        self.assertFalse(await self.redis.exists(self.lock_key))
        self.fetch_poster.assert_not_awaited()
        await self.operations.run()
        await self.request()
        await self.redis.set(self.lock_key, "replacement-owner", ex=120)
        await self.seed(**POSTER, posterStatus="ready", gameNameZh="替代工作进程的结果")
        await self.operations.run()
        self.assertEqual((await self.read())["gameNameZh"], "替代工作进程的结果")
        self.assertEqual(await self.redis.get(self.lock_key), "replacement-owner")
        for _ in range(24):
            await self.request()
        with self.assertRaises(RateLimitExceededError):
            await self.request()

    async def test_rejected_background_submit_preserves_text_and_releases_slot_and_lock(self):
        await self.seed()
        self.operations.accept = False
        with self.assertRaises(DescriptionsUnavailable):
            await self.request()
        result = await self.read()
        self.assert_verified_text(result)
        self.assertEqual(result["posterStatus"], "unavailable")
        self.assertEqual(result["posterRetryAfter"], POSTER_UNAVAILABLE_SECONDS)
        self.assertFalse(await self.redis.exists(self.lock_key))
        self.assertEqual([key async for key in self.redis.scan_iter(match=self.prefix + "slot:*")], [])
        self.fetch_poster.assert_not_awaited()
        self.describe_game.assert_not_awaited()
        self.assertIsNone(await self.redis.get(self.daily_key()))

    async def test_redis_cache_write_error_prevents_poster_io_and_preserves_old_cache(self):
        await self.seed()
        original_set = self.redis.set

        async def fail_cache(name, *args, **kwargs):
            if name == self.cache_key:
                raise RuntimeError("isolated cache write failure")
            return await original_set(name, *args, **kwargs)

        with patch.object(self.redis, "set", side_effect=fail_cache):
            with self.assertRaises(RuntimeError):
                await self.request()
        self.assert_verified_text(await self.read())
        self.assertEqual(self.operations.jobs, [])
        self.assertFalse(await self.redis.exists(self.lock_key))
        self.assertEqual([key async for key in self.redis.scan_iter(match=self.prefix + "slot:*")], [])
        self.fetch_poster.assert_not_awaited()
        self.describe_game.assert_not_awaited()
        self.assertIsNone(await self.redis.get(self.daily_key()))

    async def test_dead_poster_worker_retains_text_and_only_retries_after_lease_and_cooldown(self):
        await self.seed()
        await self.request()
        old_job = self.operations.jobs.pop()
        self.now += self.service.job_seconds + 6
        result = await self.read()
        self.assert_verified_text(result)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["posterStatus"], "unavailable")
        self.assertEqual(result["posterRetryAfter"], POSTER_UNAVAILABLE_SECONDS - 1)
        self.assertEqual((await self.request())["status"], "ready")
        self.assertEqual(self.operations.jobs, [])
        self.now += POSTER_UNAVAILABLE_SECONDS
        # The fake clock does not advance real Redis lease expiry.
        await self.redis.delete(self.lock_key)
        await self.request()
        newer_token = await self.redis.get(self.lock_key)
        await old_job[0](*old_job[1])
        self.assertEqual(await self.redis.get(self.lock_key), newer_token)
        self.assertEqual((await self.read())["status"], "pending")
        await self.operations.run()
        self.assertEqual((await self.read())["posterStatus"], "ready")
        self.describe_game.assert_not_awaited()
        self.assertIsNone(await self.redis.get(self.daily_key()))

    async def test_timeout_or_cancel_during_poster_lookup_keeps_completed_model_result(self):
        entered = asyncio.Event()

        async def blocked_poster(original):
            entered.set()
            await asyncio.Event().wait()

        self.fetch_poster.side_effect = blocked_poster
        self.service.job_seconds = 0.02
        await self.request()
        await self.operations.run()
        self.assert_verified_text(await self.read())
        self.assertEqual((await self.read())["posterStatus"], "unavailable")
        self.now += POSTER_UNAVAILABLE_SECONDS + 1
        self.service.job_seconds = 30
        entered.clear()
        await self.request()
        run = asyncio.create_task(self.operations.run())
        await asyncio.wait_for(entered.wait(), timeout=1)
        run.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await run
        self.assert_verified_text(await self.read())
        self.assertEqual((await self.read())["posterStatus"], "unavailable")
        self.describe_game.assert_awaited_once()
        self.assertEqual(await self.redis.get(self.daily_key()), "1")
        self.assertFalse(await self.redis.exists(self.lock_key))
