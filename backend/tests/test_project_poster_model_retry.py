from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock

import httpx
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from openai import APIConnectionError, APIError, APIStatusError

from backend.app.services.project_catalog.game_poster_agent import GamePosterAgent, research_game_poster
from backend.app.services.project_catalog.game_poster_resources import PosterResource
from backend.app.services.project_catalog.game_poster_retry import transient_model_failure, without_openai_sdk_retries
from backend.tests.test_project_poster_coverage import cached_image
from backend.tests.test_project_web_posters import HTML, IMAGE, ITEM, ORIGINAL, SOURCE, model_with, tool


def stream_error(code="server_error"):
    return APIError("private-provider-message", request=httpx.Request("POST", "https://model.invalid/private-token"),
                    body={"error": {"type": code, "message": "private-provider-message"}})


class PosterModelRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_error_is_retried_once_with_same_evidence_and_no_duplicate_tools(self):
        model = model_with(stream_error(), tool("search_web", {"query": ORIGINAL + " cover"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
                           AIMessage(content='{"candidateId":"image-1"}'))
        search = AsyncMock(return_value={"results": [{"url": SOURCE}]})
        fetch = AsyncMock(side_effect=[PosterResource(SOURCE, HTML, "text/html"), PosterResource(IMAGE, b"image", "image/png")])
        cache = AsyncMock(return_value=cached_image())
        agent = GamePosterAgent(model, search=search, fetch=fetch, cache=cache, model_seconds=1)
        result = await agent.run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(model.ainvoke.await_count, 5)
        self.assertIs(model.ainvoke.await_args_list[0].args[0], model.ainvoke.await_args_list[1].args[0])
        search.assert_awaited_once()
        cache.assert_awaited_once()
        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(agent.counts, {"search_web": 1, "read_page": 1, "verify_image": 1})
        self.assertTrue(all(row["status"] == "succeeded" for row in result["posterTrace"] if row.get("tool")))
        self.assertEqual(sum(row.get("stage") == "model_retry" for row in result["posterTrace"]), 1)
        self.assertNotIn("private-provider", json.dumps(result))
        self.assertNotIn("private-token", json.dumps(result))

    async def test_timeout_can_recover_without_discarding_job_evidence(self):
        calls = 0

        async def invoke(messages):
            nonlocal calls
            calls += 1
            if calls == 1:
                await asyncio.Event().wait()
            return AIMessage(content='{"candidateId":""}')

        model = model_with()
        model.ainvoke = AsyncMock(side_effect=invoke)
        agent = GamePosterAgent(model, model_seconds=0.01)
        await agent.run(ITEM)
        self.assertEqual(calls, 2)
        self.assertTrue(agent.model_retry_used)
        self.assertEqual(agent.trace[0]["error"], "model_timeout")

    async def test_second_transient_failure_exits_without_a_third_attempt(self):
        model = model_with(stream_error(), stream_error())
        result = await GamePosterAgent(model, model_seconds=1).run(ITEM)
        self.assertEqual(model.ainvoke.await_count, 2)
        self.assertEqual(result["posterStatus"], "unavailable")
        self.assertEqual(result["posterTrace"][-1]["stage"], "model_call")
        self.assertEqual(result["posterTrace"][-1]["status"], "failed")

    async def test_retry_budget_is_shared_across_model_turns(self):
        model = model_with(stream_error(), tool("search_web", {"query": ORIGINAL + " cover"}), stream_error())
        search = AsyncMock(return_value={"results": []})
        agent = GamePosterAgent(model, search=search, model_seconds=1)
        await agent.run(ITEM)
        self.assertEqual(model.ainvoke.await_count, 3)
        self.assertEqual(sum(row.get("stage") == "model_retry" for row in agent.trace), 1)
        search.assert_awaited_once()

    async def test_job_deadline_and_cancellation_are_never_retried(self):
        async def wait_forever(*args):
            await asyncio.Event().wait()
        model = model_with()
        model.ainvoke = AsyncMock(side_effect=wait_forever)
        agent = GamePosterAgent(model, deadline_seconds=0.01, model_seconds=1)
        await agent.run(ITEM)
        self.assertFalse(agent.model_retry_used)
        self.assertEqual(model.ainvoke.await_count, 1)
        model = model_with(asyncio.CancelledError())
        agent = GamePosterAgent(model)
        with self.assertRaises(asyncio.CancelledError):
            await agent.run(ITEM)
        self.assertFalse(agent.model_retry_used)

    async def test_existing_verified_image_is_returned_without_retrying_model(self):
        model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "cover"}), stream_error())
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}),
                                fetch=AsyncMock(side_effect=[PosterResource(SOURCE, HTML, "text/html"), PosterResource(IMAGE, b"image", "image/png")]),
                                cache=AsyncMock(return_value=cached_image()))
        result = await agent.run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertFalse(agent.model_retry_used)
        self.assertEqual(model.ainvoke.await_count, 4)


class RetryClassificationTests(unittest.TestCase):
    def test_explicit_nonretryable_code_overrides_generic_server_envelope(self):
        request = httpx.Request("POST", "https://model.invalid/")
        for code in ("insufficient_quota", "rate_limit_exceeded", "authentication_error", "invalid_request_error", "content_filter"):
            body = {"error": {"type": "server_error", "code": code}}
            self.assertIsNone(transient_model_failure(APIError("private", request=request, body=body)))
            self.assertIsNone(transient_model_failure(APIStatusError("private", response=httpx.Response(503, request=request), body=body)))
            self.assertIsNone(transient_model_failure(APIError("private", request=request, body={"code": code, "error": {"type": "server_error"}})))

    def test_only_explicit_transient_failures_are_eligible(self):
        request = httpx.Request("POST", "https://model.invalid/")
        for status in (400, 401, 403, 404, 422, 429):
            self.assertIsNone(transient_model_failure(APIStatusError("private", response=httpx.Response(status, request=request), body={})))
        for code in ("insufficient_quota", "invalid_request_error", "authentication_error", "content_filter", "unknown"):
            self.assertIsNone(transient_model_failure(stream_error(code)))
        for status in (408, 500, 502, 503, 504):
            self.assertEqual(transient_model_failure(APIStatusError("private", response=httpx.Response(status, request=request), body={})), "model_server_error")
        self.assertEqual(transient_model_failure(APIConnectionError(request=request)), "model_transport_failure")
        self.assertIsNone(transient_model_failure(RuntimeError("private")))


class PosterSdkRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_http_attempts_are_bounded_and_shared_client_unchanged(self):
        for status, expected in ((503, 2), (429, 1), (401, 1)):
            with self.subTest(status=status):
                requests = []

                def respond(request):
                    requests.append(request)
                    return httpx.Response(status, json={"error": {"type": "server_error", "message": "private-provider-message"}})

                transport = httpx.MockTransport(respond)
                with httpx.Client(transport=transport) as sync:
                    async with httpx.AsyncClient(transport=transport) as asynchronous:
                        base = ChatOpenAI(api_key="test-key", base_url="https://model.invalid/", model="gpt-4o",
                                          streaming=True, use_responses_api=False, max_retries=2,
                                          http_client=sync, http_async_client=asynchronous)
                        copied = without_openai_sdk_retries(base)
                        self.assertIsNot(copied, base)
                        self.assertEqual(copied.root_client.max_retries, 0)
                        self.assertEqual(copied.root_async_client.max_retries, 0)
                        result = await research_game_poster(ITEM, model=base, model_seconds=1, review=AsyncMock())
                        self.assertEqual(len(requests), expected)
                        self.assertEqual(result["posterStatus"], "unavailable")
                        self.assertEqual(base.max_retries, 2)
                        self.assertEqual(base.root_client.max_retries, 2)
                        self.assertEqual(base.root_async_client.max_retries, 2)
                        self.assertNotIn("private-provider-message", json.dumps(result))
