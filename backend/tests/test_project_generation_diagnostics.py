from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from backend.app.services.project_catalog import descriptions_service as module
from backend.tests.test_project_game_details import GAME_RESULT, REPO, metadata


class GenerationDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def service(self, **kwargs):
        instance = module.ProjectDescriptionsService(
            AsyncMock(return_value=GAME_RESULT["description_zh"]),
            describe_game=AsyncMock(return_value=dict(GAME_RESULT)), fetch=AsyncMock(return_value=metadata()),
            repository=SimpleNamespace(lookup=MagicMock(return_value={})),
            research_poster=AsyncMock(return_value={"posterStatus": "missing"}), **kwargs,
        )
        instance._finish, instance._release = AsyncMock(), AsyncMock()
        return instance

    async def generate(self, instance):
        await instance._generate(REPO, "private-lease-token", "slot", object(), True)
        instance._finish.assert_awaited_once()
        instance._release.assert_awaited_once()
        return instance._finish.await_args.args[3]

    async def test_fetch_describe_and_normalize_failures_keep_only_safe_stage_evidence(self):
        request = httpx.Request("POST", "https://user:private-password@example.test/?token=private-query")
        for stage in ("fetch", "describe", "normalize"):
            instance = self.service()
            error = httpx.HTTPStatusError("private-provider-body", request=request, response=httpx.Response(503, request=request))
            with self.subTest(stage=stage), patch.object(module, "normalize_game_details", side_effect=error if stage == "normalize" else None,
                                                       wraps=None if stage == "normalize" else module.normalize_game_details):
                if stage != "normalize":
                    getattr(instance, "fetch" if stage == "fetch" else "describe_game").side_effect = error
                result = await self.generate(instance)
            self.assertEqual(result["status"], "failed")
            trace = result["generationTrace"]
            self.assertEqual(trace[-1]["stage"], stage)
            self.assertEqual(trace[-1]["errorType"], "HTTPStatusError")
            self.assertEqual(trace[-1]["httpStatus"], 503)
            self.assertEqual(trace[-1]["status"], "failed")
            self.assertLessEqual(len(trace[-1]["errorFrames"]), 3)
            for frame in trace[-1]["errorFrames"]:
                self.assertEqual(set(frame), {"file", "function", "line"})
                self.assertNotIn("/", frame["file"])
            serialized = json.dumps(result)
            for secret in ("private-password", "private-query", "private-provider-body", "private-lease-token", "example.test"):
                self.assertNotIn(secret, serialized)
            instance.research_poster.assert_not_awaited()
            self.assertLessEqual(instance.describe_game.await_count, 1, "diagnostics must not add paid retries")

    async def test_schema_rejection_identifies_normalize_without_recording_raw_model_fields(self):
        instance = self.service()
        instance.describe_game.return_value = {"description_zh": ["private-generated-output"]}
        result = await self.generate(instance)
        self.assertEqual(result["generationTrace"][-1]["stage"], "normalize")
        self.assertEqual(result["generationTrace"][-1]["errorType"], "DescriptionInputUnavailable")
        self.assertNotIn("private-generated-output", json.dumps(result))

    async def test_successful_trace_is_internal_and_does_not_change_public_cache_read(self):
        instance = self.service()
        result = await self.generate(instance)
        self.assertEqual(result["status"], "ready")
        self.assertEqual([row["stage"] for row in result["generationTrace"]], ["fetch", "describe", "normalize", "poster"])
        self.assertTrue(all(row["status"] == "succeeded" and row["elapsedMs"] >= 0 for row in result["generationTrace"]))
        redis = SimpleNamespace(mget=AsyncMock(side_effect=[[json.dumps(result)], [None]]))
        items, _ = await instance._lookup([REPO], redis, True)
        self.assertEqual(items[0]["status"], "ready")
        self.assertNotIn("generationTrace", items[0])
        self.assertEqual(instance.describe_game.await_count, 1)

    async def test_job_deadline_preserves_the_running_stage_and_releases_the_lease(self):
        instance = self.service(job_seconds=0.02)
        cancelled = asyncio.Event()

        async def blocked(_):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        instance.describe_game.side_effect = blocked
        result = await self.generate(instance)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["generationTrace"][-1]["stage"], "describe")
        self.assertEqual(result["generationTrace"][-1]["errorType"], "CancelledError")
        self.assertEqual(instance.describe_game.await_count, 1)

    async def test_external_cancellation_propagates_and_does_not_fetch_or_retry_again(self):
        instance = self.service()
        entered = asyncio.Event()

        async def blocked(*_, **__):
            entered.set()
            await asyncio.Event().wait()

        instance.fetch.side_effect = blocked
        task = asyncio.create_task(instance._generate(REPO, "private-lease-token", "slot", object(), True))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        result = instance._finish.await_args.args[3]
        self.assertEqual(result["generationTrace"][-1]["stage"], "fetch")
        self.assertEqual(result["generationTrace"][-1]["status"], "cancelled")
        instance.fetch.assert_awaited_once()
        instance.describe_game.assert_not_awaited()
        instance._release.assert_awaited_once()
