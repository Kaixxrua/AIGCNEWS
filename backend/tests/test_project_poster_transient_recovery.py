from __future__ import annotations

import asyncio
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from curl_cffi import CurlECode
from curl_cffi.requests.exceptions import RequestException
from langchain_core.messages import AIMessage, ToolMessage

from backend.app.services.outbound_target_policy import pin_http_target
from backend.app.services.project_catalog import game_poster_resources as resources
from backend.app.services.project_catalog.game_poster_agent import GamePosterAgent
from backend.tests.test_project_poster_coverage import cached_image
from backend.tests.test_project_web_posters import HTML, IMAGE, ITEM, ORIGINAL, SOURCE, image_bytes, model_with, tool


def response(status=200, content_type="image/png", body=b"valid body", **headers):
    return SimpleNamespace(status_code=status, headers={"content-type": content_type, **headers}, body=body)


def transient(code=CurlECode.OPERATION_TIMEDOUT, http_status=0):
    return RequestException("private-transport-message", code=code, response=SimpleNamespace(status_code=http_status))


class ImageRetryTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def public(url, **kwargs):
        return pin_http_target(url, resolver=lambda _: ["93.184.216.34"], **kwargs)

    def session(self, actions, seen):
        actions = iter(actions)

        class Session:
            def __init__(self, **options):
                assert options["verify"] is True
                assert options["curl_options"][resources.CurlOpt.MAXFILESIZE_LARGE] <= resources.IMAGE_BYTES
                self.options = options

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                seen.append({"closed": True})

            async def get(self, url, *, allow_redirects, timeout, content_callback):
                assert not allow_redirects
                seen.append({"url": url, "timeout": timeout})
                action = next(actions)
                if callable(action):
                    action = await action()
                if isinstance(action, Exception):
                    # Partial transfer bytes must not survive into a retry.
                    content_callback(b"partial")
                    raise action
                if content_callback(action.body) == resources.CURL_WRITEFUNC_ERROR:
                    raise transient(CurlECode.RECV_ERROR)
                return action
        return Session

    async def test_known_transient_retry_repins_and_discards_partial_bytes(self):
        for code in (CurlECode.OPERATION_TIMEDOUT, CurlECode.COULDNT_CONNECT, CurlECode.RECV_ERROR,
                     CurlECode.SEND_ERROR, CurlECode.GOT_NOTHING):
            seen = []
            with self.subTest(code=code), patch.object(resources, "pin_http_target", side_effect=self.public) as pin, \
                    patch.object(resources, "AsyncSession", self.session([transient(code), response()], seen)):
                result = await resources.fetch_poster_resource(IMAGE, image=True)
                self.assertEqual(result.body, b"valid body")
                self.assertEqual(pin.call_count, 2)
                self.assertTrue(all(c.kwargs["reject_mixed"] for c in pin.call_args_list))
            self.assertEqual(len([x for x in seen if x.get("closed")]), 2)
            self.assertTrue(all(0 < x["timeout"] <= 18 for x in seen if "timeout" in x))

    async def test_second_transport_failure_stops_without_third_attempt(self):
        seen = []
        with patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session([transient(), transient()], seen)):
            with self.assertRaisesRegex(resources.PosterResourceError, "^network_unavailable$") as raised:
                await resources.fetch_poster_resource(IMAGE, image=True)
        self.assertNotIn("private-transport-message", str(raised.exception))
        self.assertEqual(len([x for x in seen if "url" in x]), 2)

    async def test_rejections_unknown_errors_and_html_are_not_retried(self):
        cases = [response(403), response(429), response(404), response(content_type="text/html"),
                 transient(http_status=429), transient(http_status=403), RuntimeError("unknown"),
                 transient(CurlECode.PEER_FAILED_VERIFICATION), transient(CurlECode.FILESIZE_EXCEEDED)]
        for action in cases:
            seen = []
            with self.subTest(action=type(action).__name__), patch.object(resources, "pin_http_target", self.public), \
                    patch.object(resources, "AsyncSession", self.session([action], seen)):
                with self.assertRaises(resources.PosterResourceError):
                    await resources.fetch_poster_resource(IMAGE, image=True)
            self.assertEqual(len([x for x in seen if "url" in x]), 1)

    async def test_page_download_keeps_its_existing_limit_and_no_retry(self):
        seen = []
        with patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session([transient()], seen)):
            with self.assertRaises(resources.PosterResourceError):
                await resources.fetch_poster_resource(SOURCE)
        self.assertEqual(len([x for x in seen if "url" in x]), 1)
        self.assertLessEqual(seen[0]["timeout"], 12)

    async def test_size_limit_wins_over_transient_callback_error(self):
        seen = []
        with patch.object(resources, "IMAGE_BYTES", 8), patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session([response(body=b"x" * 9)], seen)):
            with self.assertRaisesRegex(resources.PosterResourceError, "^image_too_large$"):
                await resources.fetch_poster_resource(IMAGE, image=True)
        self.assertEqual(len([x for x in seen if "url" in x]), 1)

    async def test_retry_rejects_dns_rebinding_before_second_connection(self):
        calls, seen = [], []

        def pin(url, **kwargs):
            calls.append(url)
            ips = ["93.184.216.34"] if len(calls) == 1 else ["93.184.216.34", "127.0.0.1"]
            return pin_http_target(url, resolver=lambda _: ips, **kwargs)

        with patch.object(resources, "pin_http_target", pin), \
                patch.object(resources, "AsyncSession", self.session([transient()], seen)):
            with self.assertRaises(resources.PosterResourceError):
                await resources.fetch_poster_resource(IMAGE, image=True)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len([x for x in seen if "url" in x]), 1)

    async def test_retry_preserves_redirect_pin_and_total_hop_limit(self):
        seen = []
        redirect = response(302, body=b"", location=IMAGE + "?next=1")
        with patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session([redirect, transient(), response()], seen)):
            result = await resources.fetch_poster_resource(IMAGE, image=True)
        self.assertEqual(result.url, IMAGE + "?next=1")
        self.assertEqual([x["url"] for x in seen if "url" in x], [IMAGE, result.url, result.url])
        seen = []
        with patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session([transient()] + [redirect] * 4, seen)):
            with self.assertRaisesRegex(resources.PosterResourceError, "^too_many_redirects$"):
                await resources.fetch_poster_resource(IMAGE, image=True)
        self.assertEqual(len([x for x in seen if "url" in x]), 5)

    async def test_retry_shares_total_deadline(self):
        async def delayed_failure():
            await asyncio.sleep(0.05)
            return transient()

        async def blocked():
            await asyncio.Event().wait()

        seen, started = [], time.monotonic()
        with patch.object(resources, "IMAGE_RESOURCE_SECONDS", 0.2), patch.object(resources, "IMAGE_REQUEST_SECONDS", 0.18), \
                patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session([delayed_failure, blocked], seen)):
            with self.assertRaisesRegex(resources.PosterResourceError, "^network_unavailable$"):
                await resources.fetch_poster_resource(IMAGE, image=True)
        self.assertLess(time.monotonic() - started, 0.6)
        requests = [x for x in seen if "timeout" in x]
        self.assertEqual(len(requests), 2)
        self.assertLess(requests[1]["timeout"], requests[0]["timeout"])
        self.assertEqual(len([x for x in seen if x.get("closed")]), 2)

    async def test_cancellation_during_each_attempt_closes_without_further_retry(self):
        for on_retry in (False, True):
            entered, seen = asyncio.Event(), []

            async def blocked():
                entered.set()
                await asyncio.Event().wait()

            actions = ([transient()] if on_retry else []) + [blocked]
            with self.subTest(on_retry=on_retry), patch.object(resources, "pin_http_target", self.public), \
                    patch.object(resources, "AsyncSession", self.session(actions, seen)):
                task = asyncio.create_task(resources.fetch_poster_resource(IMAGE, image=True))
                await asyncio.wait_for(entered.wait(), 1)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 1)
            self.assertEqual(len([x for x in seen if "url" in x]), 2 if on_retry else 1)
            self.assertTrue(seen[-1]["closed"])

    async def test_valid_retry_consumes_one_candidate_and_reviews_only_after_download(self):
        seen = []
        async def fetch(url, *, image=False):
            return await resources.fetch_poster_resource(url, image=True) if image else resources.PosterResource(SOURCE, HTML, "text/html")

        model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}), tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "cover"}), AIMessage(content='{"candidateId":"image-1"}'))
        review = AsyncMock(return_value={"matches": True, "kind": "cover", "reason": "matched"})
        cache = AsyncMock(return_value=cached_image())
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}), fetch=fetch, review=review, cache=cache)
        with patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session([transient(), response(body=image_bytes())], seen)):
            result = await agent.run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(agent.counts["verify_image"], 1)
        review.assert_awaited_once()
        cache.assert_awaited_once()
        terminal = result["posterTrace"][-1]["terminal"]
        self.assertEqual((terminal["reason"], terminal["modelTurns"]), ("verified", 4))


class RecoveryVisibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_unused_recovery_is_numeric_even_with_zero_regular_searches(self):
        item = {**ITEM, "detailsVersion": 1}
        reads = AIMessage(content="", tool_calls=[
            {"name": "read_page", "args": {"resultId": "page-1"}, "id": "a", "type": "tool_call"},
            {"name": "read_page", "args": {"resultId": "page-2"}, "id": "b", "type": "tool_call"},
        ])
        empty = AIMessage(content='{"candidateId":""}')
        model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}), reads,
                           tool("search_web", {"query": ORIGINAL + " official", "searchType": "pages"}), empty, empty)
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}, {"url": SOURCE + "/b"}]}),
                                search_pages=AsyncMock(side_effect=resources.PosterResourceError("search_unavailable")),
                                fetch=AsyncMock(side_effect=resources.PosterResourceError("network_unavailable")))
        result = await agent.run(item)
        messages = [json.loads(m.content) for m in model.ainvoke.call_args.args[0] if isinstance(m, ToolMessage)]
        self.assertEqual(messages[-1]["remainingBudget"]["search_web"], 0)
        self.assertEqual(messages[-1]["recoveryBudget"]["additional"], {"search_web": 1, "read_page": 2, "verify_image": 1})
        self.assertTrue(messages[-1]["recoveryBudget"]["eligible"])
        terminal = result["posterTrace"][-1]["terminal"]
        self.assertEqual((terminal["reason"], terminal["modelTurns"]), ("model_empty_result", 5))
        self.assertEqual(terminal["counts"], {"search_web": 2, "read_page": 2, "verify_image": 0})
        self.assertFalse(terminal["recoveryBudget"]["used"])

    async def test_recovery_does_not_double_count_a_still_available_regular_search(self):
        agent = GamePosterAgent(model_with())
        agent.source_recovery = True
        agent.counts.update(search_web=1, verify_image=3)
        budget = agent._budget_view()
        self.assertEqual(budget["remainingBudget"]["search_web"], 1)
        self.assertTrue(budget["recoveryBudget"]["eligible"])
        self.assertEqual(budget["recoveryBudget"]["additional"]["search_web"], 0)
        agent.project_recovery_used = True
        self.assertEqual(agent._recovery_budget()["additional"], {"search_web": 0, "read_page": 0, "verify_image": 0})

    async def test_terminal_distinguishes_unverified_final_and_turn_limit_without_raw_output(self):
        search = AsyncMock(return_value={"results": []})
        model = model_with(tool("search_web", {"query": ORIGINAL}), AIMessage(content='{"candidateId":"private-model-string"}'))
        result = await GamePosterAgent(model, search=search).run(ITEM)
        self.assertEqual(result["posterTrace"][-1]["terminal"]["reason"], "unverified_candidate")
        self.assertNotIn("private-model-string", json.dumps(result))
        model = model_with(*(tool("search_web", {"query": ORIGINAL}) for _ in range(8)))
        result = await GamePosterAgent(model, search=search).run(ITEM)
        terminal = result["posterTrace"][-1]["terminal"]
        self.assertEqual((terminal["reason"], terminal["modelTurns"]), ("model_turn_limit", 8))
