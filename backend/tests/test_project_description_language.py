from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI
from pydantic import ValidationError

from backend.app.api import routes_project_descriptions as routes
from backend.app.api.dependencies import get_project_descriptions_service
from backend.app.models.schema_project_descriptions import ProjectDescriptionRequest
from backend.app.services.project_catalog import descriptions_service as service_module
from backend.app.services.project_catalog.description_language import chinese_description, description_validation_reason
from backend.app.services.project_catalog.game_details import normalize_game_details
from backend.app.services.project_catalog.game_identity_context import identity_evidence
from backend.app.services.project_catalog.generation_diagnostics import generation_stage
from backend.tests.test_project_descriptions import QueuedOperations

REPO = "gorisanson/pikachu-volleyball"
TITLE = "対戦ぴかちゅ～　ﾋﾞｰﾁﾊﾞﾚｰ編"
# Real primary README introduction, blob b5cde665ddc87f577c14de4d81c9c6b3df14c101:
# https://github.com/gorisanson/pikachu-volleyball/blob/main/README.md
README = (
    '# Pikachu Volleyball\n\nPikachu Volleyball (対戦ぴかちゅ～　ﾋﾞｰﾁﾊﾞﾚｰ編) is an old Windows game '
    'that was developed by "(C) SACHI SOFT / SAWAYAKAN Programmers" and "(C) Satoshi Takenouchi" in 1997. '
    'The source code on this repository was obtained by reverse engineering the core parts of the machine code '
    '&mdash; including the physics engine and the AI &mdash; of the original game and reimplementing them in JavaScript.\n'
    'You can play this game on the website: https://gorisanson.github.io/pikachu-volleyball/en/'
)
METADATA = {"full_name": REPO, "description": "Pikachu Volleyball reimplemented in JavaScript by reverse engineering the original game", "readme_text": README}
ZH = f"这是经典排球游戏《{TITLE}》的 JavaScript 重实现，通过逆向还原物理引擎和电脑 AI，可在浏览器中游玩。"
MODEL = {"description_zh": ZH, "game_identity": "single_game", "game_name_original": TITLE,
         "game_name_zh": "皮卡丘排球", "poster_candidate_id": "", "poster_kind": ""}


def game_record(metadata=None, data=None):
    metadata = METADATA if metadata is None else metadata
    return {"repo": REPO, "status": "ready", "descriptionZh": ZH,
            **normalize_game_details(MODEL if data is None else data, metadata),
            "gameIdentityEvidence": identity_evidence(metadata)}


class DescriptionLanguageTests(unittest.TestCase):
    def test_only_exact_quoted_verified_title_is_exempt_and_display_is_unchanged(self):
        game = game_record()
        self.assertEqual(game["gameNameOriginal"], TITLE)
        for left, right in (("《", "》"), ("〈", "〉"), ("「", "」"), ("『", "』"), ("“", "”"), ("‘", "’"), ('"', '"'), ("'", "'")):
            value = ZH.replace(f"《{TITLE}》", left + TITLE + right)
            with self.subTest(quote=left):
                self.assertEqual(chinese_description(value, game=game), value)
                self.assertEqual(description_validation_reason(value, game=game), "")

    def test_japanese_prose_unsupported_aliases_and_non_game_context_stay_rejected(self):
        for value in (TITLE, f"《{TITLE}》", f"これは《{TITLE}》のゲームです。", f"A port of《{TITLE}》.",
                      ZH + "楽しめる", ZH + "ゲーム", ZH + "ﾀﾉｼｲ", ZH.replace("《", "").replace("》", ""),
                      ZH.replace("》", "」"), ZH.replace(TITLE, TITLE + " 2")):
            with self.subTest(value=value):
                self.assertEqual(chinese_description(value, game=game_record()), "")
        for game in (None, {"gameNameOriginal": TITLE}, {**game_record(), "gameIdentityEvidence": {}},
                     game_record(data={**MODEL, "game_identity": "unknown"}),
                     game_record(data={**MODEL, "game_name_original": "Pikachu Volleyball"}),
                     game_record(metadata={**METADATA, "readme_text": "No title evidence."}),
                     {**game_record(), "identityEvidenceVersion": 0},
                     {**game_record(), "repo": "https://example.test/not-a-repo"}):
            with self.subTest(game=game):
                self.assertEqual(chinese_description(ZH, game=game), "")

    def test_language_and_length_failure_reasons_are_bounded(self):
        for value, reason in ((None, "invalid_type"), (["private response"], "invalid_type"), ("  ", "empty"),
                              ("中" * 513, "too_long"), ("English only", "no_han"), ("中文ゲーム", "kana_present")):
            with self.subTest(reason=reason):
                self.assertEqual(description_validation_reason(value, game=game_record()), reason)
        exact = ZH + "中" * (512 - len(ZH))
        self.assertEqual(chinese_description(exact, game=game_record()), exact)
        self.assertEqual(chinese_description(exact + "中", game=game_record()), "")

    def test_internal_evidence_versions_must_be_integers_not_bool_float_or_strings(self):
        game = game_record()
        self.assertEqual(chinese_description(ZH, game=game), ZH)
        for field, values in (("detailsVersion", (True, 1.0, "1", None)),
                              ("identityEvidenceVersion", (True, 2.0, "2", None))):
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assertEqual(chinese_description(ZH, game={**game, field: value}), "")

    def test_caller_cannot_supply_an_exception_or_internal_identity_context(self):
        for key, value in (("allowedTitles", [TITLE]), ("gameNameOriginal", TITLE), ("gameIdentityEvidence", identity_evidence(METADATA))):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                ProjectDescriptionRequest.model_validate({"repo": REPO, "gameDetails": True, key: value})


class MemoryCache:
    """Only the fenced-cache protocol used here, with no external Redis access."""
    def __init__(self):
        self.values = {}

    async def mget(self, keys):
        return [self.values.get(key) for key in keys]

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script, count, *args):
        keys, values = args[:count], args[count:]
        if self.values.get(keys[0]) != values[0]:
            return 0
        if script == service_module._FINISH:
            self.values[keys[1]] = values[1]
        else:
            assert script == service_module._RELEASE
        self.values.pop(keys[0], None)
        return 1


class DescriptionLanguageFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 1794330000.0
        self.cache = MemoryCache()
        self.fetch = AsyncMock(return_value=dict(METADATA))
        self.describe = AsyncMock(return_value=dict(MODEL))
        self.research = AsyncMock(return_value={"posterStatus": "missing"})
        self.service = service_module.ProjectDescriptionsService(
            AsyncMock(), describe_game=self.describe, fetch=self.fetch, research_poster=self.research,
            repository=SimpleNamespace(lookup=MagicMock(return_value={})), clock=lambda: self.now,
        )
        self.key = service_module.PREFIX + "cache:game-v1:" + REPO
        self.lock = service_module.PREFIX + "lock:game-v1:" + REPO
        self.operations = QueuedOperations()
        self.authorization = SimpleNamespace(user_id=123)
        self.rate = patch.object(service_module, "hit_rate_limit", new=AsyncMock())
        self.charge = patch.object(service_module, "charge_generation", new=AsyncMock())
        self.rate.start()
        self.charge.start()

    async def asyncTearDown(self):
        self.rate.stop()
        self.charge.stop()

    async def generate(self):
        await self.cache.set(self.lock, "offline-token")
        await self.service._generate(REPO, "offline-token", "slot", self.cache, True)
        return json.loads(self.cache.values[self.key])

    async def lookup(self):
        return (await self.service._lookup([REPO], self.cache, True))[0][0]

    async def refresh(self):
        return await self.service.request(REPO, redis=self.cache, authorization=self.authorization,
                                          operations=self.operations, game_details=True, refresh_poster=True)

    async def test_real_readme_generation_public_get_and_poster_only_refresh_keep_same_description(self):
        stored = await self.generate()
        self.assertEqual(stored["status"], "ready")
        self.assertEqual(stored["descriptionZh"], ZH)
        self.assertEqual((await self.lookup())["descriptionZh"], ZH)
        app = FastAPI()
        app.include_router(routes.router, prefix="/api")
        app.state.redis = self.cache
        app.dependency_overrides[get_project_descriptions_service] = lambda: self.service
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/projects/descriptions", params={"repos": REPO, "gameDetails": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["descriptionZh"], ZH)
        self.assertNotIn("gameIdentityEvidence", response.text)
        self.assertNotIn("generationTrace", response.text)
        self.assertNotIn("validationReason", response.text)
        self.now += 3601
        pending = await self.refresh()
        self.assertEqual(pending["status"], "pending")
        self.assertEqual((await self.lookup())["descriptionZh"], ZH)
        self.assertTrue(json.loads(self.cache.values[self.key])["posterOnly"])
        self.assertEqual(self.operations.jobs[0][0].__name__, "_generate_poster")
        await self.operations.run()
        self.assertEqual((await self.lookup())["descriptionZh"], ZH)
        self.fetch.assert_awaited_once()
        self.describe.assert_awaited_once()
        self.assertEqual(self.research.await_count, 2)

    async def test_interrupted_poster_only_worker_preserves_valid_text_and_cooldown(self):
        await self.generate()
        self.now += 3601
        await self.refresh()
        pending = json.loads(self.cache.values[self.key])
        self.operations.jobs.clear()
        self.now = pending["deadline"] + 10
        ready = await self.lookup()
        self.assertEqual((ready["status"], ready["descriptionZh"]), ("ready", ZH))
        self.assertGreater(ready["posterRetryAfter"], 0)
        self.assertEqual(json.loads(self.cache.values[self.key]), pending, "GET is read-only")

    async def test_failed_new_evidence_does_not_invalidate_previous_cache_description(self):
        existing = await self.generate()
        for source in ({**METADATA, "readme_text": "A new README without the title."}, RuntimeError("private provider details")):
            self.fetch.side_effect = source if isinstance(source, Exception) else None
            if isinstance(source, dict):
                self.fetch.return_value = source
            with self.subTest(source=type(source).__name__):
                refreshed, project_only = await self.service._refresh_identity_evidence(existing)
                self.assertTrue(project_only)
                self.assertEqual(refreshed, existing)
                self.cache.values[self.key] = json.dumps(refreshed)
                self.assertEqual((await self.lookup())["descriptionZh"], ZH)

    async def test_identity_repair_uses_new_evidenced_name_for_chinese_validation(self):
        old = {**game_record(), "gameNameOriginal": "Old Name", "descriptionZh": "已核实的旧版中文说明。"}
        current, project_only = await self.service._refresh_identity_evidence(old, repair_identity=True)
        self.assertFalse(project_only)
        self.assertEqual(current["gameNameOriginal"], TITLE)
        self.assertEqual(current["descriptionZh"], old["descriptionZh"])
        # A conflict repairs the description too; exact Japanese title remains legal.
        old["gameNameOriginal"] = "Game (Version 1.1, English)"
        self.fetch.return_value = {**METADATA, "readme_text": README + "\nGame (Version 1.1, English) requires exact matching machine code."}
        current, project_only = await self.service._refresh_identity_evidence(old)
        self.assertFalse(project_only)
        self.assertEqual(current["descriptionZh"], ZH)
        self.cache.values[self.key] = json.dumps(current)
        self.assertEqual((await self.lookup())["descriptionZh"], ZH)

    async def test_shorter_cached_evidence_does_not_write_ready_that_get_would_drop(self):
        self.fetch.return_value = {**METADATA, "readme_text": "x" * 6001 + README}
        result = await self.generate()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["generationTrace"][-1]["validationReason"], "kana_present")
        self.research.assert_not_awaited()

    async def test_failures_record_only_safe_reason_and_never_generated_text(self):
        for value, reason in (([], "invalid_type"), ("", "empty"), ("中" * 513, "too_long"),
                              ("private-only-english", "no_han"), ("中文ゲーム private-provider-secret", "kana_present")):
            self.describe.return_value = {**MODEL, "description_zh": value}
            with self.subTest(reason=reason):
                result = await self.generate()
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["generationTrace"][-1]["validationReason"], reason)
                self.assertNotIn("private-", json.dumps(result))
                self.research.assert_not_awaited()

    async def test_trace_drops_untrusted_reason_and_non_string_values(self):
        for value in ("private-provider-message", {"private": "body"}, "kana_present"):
            trace = []
            error = RuntimeError("private exception body")
            error.validation_reason = value
            with self.assertRaises(RuntimeError):
                async with generation_stage(trace, "normalize"):
                    raise error
            self.assertEqual(trace[0].get("validationReason"), "kana_present" if value == "kana_present" else None)
            self.assertNotIn("private", json.dumps(trace))
