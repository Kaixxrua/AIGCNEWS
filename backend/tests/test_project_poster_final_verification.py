from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

from backend.app.services.project_catalog import game_poster_agent as agent_module
from backend.app.services.project_catalog.game_poster_agent import GamePosterAgent
from backend.app.services.project_catalog.game_poster_resources import PosterResource, PosterResourceError
from backend.tests.test_project_poster_coverage import cached_image
from backend.tests.test_project_web_posters import ITEM, ORIGINAL, image_bytes, model_with, tool


def verify(identifier="image-1"):
    return tool("verify_image", {"candidateId": identifier, "kind": "screenshot"})


class LatePage:
    """Exercise real search/read registration through an 8- or 11-turn run."""

    def __init__(self, tail=None, *, recovery=False, early_image=False, final_empty=False):
        self.pages = [f"https://page{index}.example/game" for index in range(8 if recovery else 6)]
        self.image = "https://images.example/whole-game.png"

        def search():
            return tool("search_web", {"query": ORIGINAL + " screenshots"})

        def read(index):
            return tool("read_page", {"resultId": f"page-{index}"})

        if recovery:
            responses = [search(), read(1), read(2), search(), search(), *(read(index) for index in range(3, 9))]
            search_results = [self.pages[:6], self.pages[6:], []]
        else:
            responses = [search(), *(read(index) for index in range(1, 6)), search(), read(6)]
            search_results = [self.pages, []]
        self.turns = len(responses)
        self.responses = [*responses, verify() if tail is None else tail]
        self.response_index = 0
        self.before_last_read = None
        self.image_action = None

        async def respond(_messages):
            response = self.responses[self.response_index]
            self.response_index += 1
            if isinstance(response, BaseException):
                raise response
            return await response() if callable(response) else response

        async def fetch(url, image=False):
            if image:
                if self.image_action:
                    return await self.image_action()
                return PosterResource(url, image_bytes(), "image/png")
            if recovery and url in self.pages[:2]:
                raise PosterResourceError("network_unavailable")
            last = url == self.pages[-1]
            if last and self.before_last_read:
                self.before_last_read()
            visible = (last and not final_empty) or (url == self.pages[0] and early_image)
            image_url = self.image if last else "https://images.example/earlier-game.png"
            body = f'<h1>{ORIGINAL}</h1>' + (f'<img src="{image_url}" alt="Complete game screenshot">' if visible else '')
            return PosterResource(url, body.encode(), "text/html")

        self.model = model_with()
        self.model.ainvoke = AsyncMock(side_effect=respond)
        self.search = AsyncMock(side_effect=[{"results": [{"url": url} for url in urls]} for urls in search_results])
        self.fetch = AsyncMock(side_effect=fetch)
        self.review = AsyncMock(return_value={"matches": True, "kind": "screenshot", "reason": "matched"})
        self.cache = AsyncMock(return_value=cached_image())
        self.agent = GamePosterAgent(self.model, search=self.search, fetch=self.fetch, review=self.review, cache=self.cache)

    async def run(self):
        return await self.agent.run({**ITEM, "detailsVersion": 1})

    def assert_no_image_work(self, test):
        test.assertFalse(any(call.kwargs.get("image") for call in self.fetch.await_args_list))
        self.review.assert_not_awaited()
        self.cache.assert_not_awaited()


class PosterFinalVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_last_read_gets_one_existing_verification_without_prior_image_failure(self):
        for recovery in (False, True):
            with self.subTest(recovery=recovery):
                case = LatePage(recovery=recovery)
                result = await case.run()
                self.assertEqual(result["posterStatus"], "ready")
                self.assertEqual(result["posterSourceUrl"], case.pages[-1])
                self.assertEqual(case.model.ainvoke.await_count, case.turns + 1)
                self.assertEqual(case.agent.limits, {"search_web": 3 if recovery else 2, "read_page": 8 if recovery else 6, "verify_image": 4 if recovery else 3})
                self.assertEqual(case.agent.counts, {"search_web": 3 if recovery else 2, "read_page": 8 if recovery else 6, "verify_image": 1})
                self.assertFalse(case.agent.model_retry_used)
                case.review.assert_awaited_once()
                case.cache.assert_awaited_once()
                self.assertEqual(case.review.await_args.kwargs["candidate"]["sourceUrl"], case.pages[-1])
                self.assertEqual(case.cache.await_args.args[0], image_bytes())
                self.assertEqual([entry["function"]["name"] for entry in case.model.bind_tools.call_args.args[0]], ["verify_image"])
                messages = case.model.ainvoke.await_args.args[0]
                self.assertEqual(json.loads(messages[-1].content)["allowedCandidateIds"], ["image-1"])
                self.assertIn("先按来源上下文把核图额度留给完整游戏场景", messages[0].content)
                tail = next(row for row in result["posterTrace"] if row.get("stage") == "final_verification")
                self.assertEqual(tail["candidateIds"], ["image-1"])
                self.assertGreater(tail["remainingMs"], 20000)
                self.assertEqual(result["posterTrace"][-1]["terminal"]["modelTurns"], case.turns + 1)
                self.assertTrue(result["posterTrace"][-1]["finalVerification"])

    async def test_tail_rejects_unknown_old_ids_multiple_calls_and_search_before_dispatch(self):
        mixed = AIMessage(content="", tool_calls=[
            {"name": "verify_image", "args": {"candidateId": "image-1", "kind": "cover"}, "id": "a"},
            {"name": "search_web", "args": {"query": ORIGINAL}, "id": "b"},
        ])
        multiple = AIMessage(content="", tool_calls=[
            {"name": "verify_image", "args": {"candidateId": "image-1", "kind": "cover"}, "id": str(index)} for index in range(2)
        ])
        for response in (verify("image-999-private-value"), mixed, multiple,
                         tool("search_web", {"query": ORIGINAL}), tool("read_page", {"resultId": "page-1"}),
                         tool("verify_image", {"candidateId": "image-1", "kind": "cover", "url": "private-value"})):
            with self.subTest(response=response.tool_calls):
                case = LatePage(response)
                result = await case.run()
                case.assert_no_image_work(self)
                self.assertEqual(case.agent.counts["verify_image"], 0)
                self.assertEqual(case.search.await_count, 2)
                self.assertEqual(case.model.ainvoke.await_count, 9)
                self.assertEqual(result["posterTrace"][-1]["error"], "invalid_final_verification")
                self.assertNotIn("private-value", json.dumps(result))
        old = LatePage(verify("image-1"), early_image=True)
        result = await old.run()
        old.assert_no_image_work(self)
        self.assertEqual(result["posterTrace"][-1]["candidateIds"], ["image-2"])
        self.assertEqual(result["posterTrace"][-1]["error"], "invalid_final_verification")

    async def test_no_new_candidates_no_image_budget_or_insufficient_deadline_never_selects(self):
        for guard in ("empty", "budget", "time", "tried"):
            with self.subTest(guard=guard):
                case = LatePage(final_empty=guard == "empty", early_image=guard == "empty")
                if guard == "budget":
                    case.agent.counts["verify_image"] = case.agent.limits["verify_image"]
                elif guard == "time":
                    case.before_last_read = lambda: setattr(case.agent, "deadline", asyncio.get_running_loop().time() + 0.05)
                elif guard == "tried":
                    accept = case.agent._accept

                    def mark_tried(*args):
                        result = accept(*args)
                        for candidate in case.agent.candidates.values():
                            case.agent.attempted_images.add(case.agent._image_evidence(candidate))
                        return result

                    case.agent._accept = mark_tried
                result = await case.run()
                case.assert_no_image_work(self)
                self.assertEqual(case.model.ainvoke.await_count, 8)
                self.assertFalse(any(row.get("stage") == "final_verification" for row in result["posterTrace"]))
                self.assertEqual(result["posterTrace"][-1]["terminal"]["reason"], "model_turn_limit")

    async def test_failed_final_read_does_not_offer_older_candidates(self):
        case = LatePage(recovery=True)
        case.before_last_read = lambda: (_ for _ in ()).throw(PosterResourceError("network_unavailable"))
        result = await case.run()
        case.assert_no_image_work(self)
        self.assertEqual(case.model.ainvoke.await_count, 11)
        self.assertFalse(any(row.get("stage") == "final_verification" for row in result["posterTrace"]))

    async def test_explicit_final_empty_is_respected_and_existing_verified_result_needs_no_tail(self):
        case = LatePage()
        case.responses[6:8] = [tool("read_page", {"resultId": "page-6"}), AIMessage(content='{"candidateId":""}')]
        result = await case.run()
        case.assert_no_image_work(self)
        self.assertEqual(case.model.ainvoke.await_count, 8)
        self.assertEqual(result["posterTrace"][-1]["terminal"]["reason"], "model_empty_result")
        case = LatePage(early_image=True)
        case.responses[:8] = [tool("search_web", {"query": ORIGINAL}), tool("read_page", {"resultId": "page-1"}), verify(),
                              *(tool("read_page", {"resultId": f"page-{index}"}) for index in range(2, 7))]
        result = await case.run()
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(result["posterSourceUrl"], case.pages[0])
        case.review.assert_awaited_once()
        case.cache.assert_awaited_once()
        case.model.bind_tools.assert_called_once()
        self.assertEqual(case.model.ainvoke.await_count, 8)
        self.assertEqual(result["posterTrace"][-1]["terminal"]["reason"], "model_turn_limit")

    async def test_empty_selection_provider_failure_and_image_mismatch_stop_without_retry(self):
        for failure in ("empty", "empty_tool", "provider", "mismatch"):
            with self.subTest(failure=failure):
                case = LatePage(AIMessage(content='{"candidateId":""}') if failure == "empty" else TimeoutError() if failure == "provider" else verify())
                if failure == "empty_tool":
                    case.responses[-1] = verify("")
                if failure == "mismatch":
                    case.review.return_value = {"matches": False, "kind": "screenshot", "reason": "uncertain"}
                result = await case.run()
                self.assertNotEqual(result["posterStatus"], "ready")
                self.assertEqual(case.model.ainvoke.await_count, 9)
                self.assertFalse(case.agent.model_retry_used)
                case.cache.assert_not_awaited()
                if failure == "mismatch":
                    case.review.assert_awaited_once()
                    self.assertEqual(result["posterTrace"][-1]["imageReview"]["reason"], "uncertain")
                    self.assertEqual(case.agent.counts["verify_image"], 1)
                else:
                    case.assert_no_image_work(self)
                    if failure in {"empty", "empty_tool"}:
                        self.assertEqual(result["posterTrace"][-1]["status"], "skipped")
                        self.assertEqual(result["posterTrace"][-1]["reason"], "no_selection")

    async def test_tail_model_timeout_has_no_retry_and_original_deadline_still_cancels_image_work(self):
        cancelled = asyncio.Event()

        async def blocked():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        case = LatePage(blocked)
        with patch.object(agent_module, "FINAL_VERIFY_MODEL_SECONDS", 0.01):
            result = await case.run()
        self.assertTrue(cancelled.is_set())
        self.assertEqual(case.model.ainvoke.await_count, 9)
        self.assertEqual(result["posterTrace"][-1]["error"], "model_timeout")
        case.assert_no_image_work(self)
        cancelled.clear()
        case = LatePage()

        async def nearly_expired():
            case.agent.deadline = asyncio.get_running_loop().time() + 0.02
            return verify()

        case.responses[-1] = nearly_expired
        case.image_action = blocked
        result = await case.run()
        self.assertTrue(cancelled.is_set())
        self.assertEqual(result["posterTrace"][-1]["error"], "agent_deadline")
        self.assertEqual(case.model.ainvoke.await_count, 9)
        case.review.assert_not_awaited()
        case.cache.assert_not_awaited()

    async def test_external_cancellation_during_selection_or_verification_propagates(self):
        for phase in ("selection", "verification"):
            with self.subTest(phase=phase):
                entered, cancelled = asyncio.Event(), asyncio.Event()

                async def blocked():
                    entered.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cancelled.set()

                case = LatePage(blocked if phase == "selection" else verify())
                if phase == "verification":
                    case.image_action = blocked
                task = asyncio.create_task(case.run())
                await asyncio.wait_for(entered.wait(), 1)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(cancelled.is_set())
                self.assertEqual(case.model.ainvoke.await_count, 9)
                self.assertEqual(case.agent.trace[-1]["terminal"]["reason"], "cancelled")
                self.assertEqual(case.agent.trace[-1]["terminal"]["modelTurns"], 9)
                case.cache.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
