from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from curl_cffi.requests.exceptions import RequestException
from langchain_core.messages import AIMessage

from backend.app.services.outbound_target_policy import pin_http_target
from backend.app.services.project_catalog import game_poster_resources as resources
from backend.app.services.project_catalog.game_poster_agent import GamePosterAgent, page_images
from backend.app.services.project_catalog.game_poster_page_identity import (
    project_media_descendant,
    project_media_directory,
)
from backend.tests.test_project_poster_coverage import cached_image
from backend.tests.test_project_web_posters import model_with, tool

REPO = "author/free-world"
SOURCE = "https://github.com/author/free-world/tree/main/screenshots/gameplay"
CHILD = SOURCE + "/13_inches"
DETAIL = CHILD.replace("/tree/", "/blob/") + "/gameplay.png"
RAW = DETAIL + "?raw=true"


def html(*links: str, image: str = "") -> bytes:
    return ('<h1>Free World screenshots</h1>' + ''.join(f'<a href="{link}">gameplay</a>' for link in links)
            + (f'<img src="{image}" alt="Free World gameplay">' if image else "")).encode()


class PageLimitTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def public(url, **kwargs):
        return pin_http_target(url, resolver=lambda _: ["93.184.216.34"], **kwargs)

    @staticmethod
    def response(body=b"<h1>Free World</h1>", status=200, content_type="text/html", **headers):
        return SimpleNamespace(body=body, status_code=status, headers={"content-type": content_type, **headers})

    def session(self, actions, seen):
        actions = iter(actions)

        class Session:
            def __init__(self, **options):
                self.options = options
                assert options["verify"] is True

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                seen.append({"closed": True})

            async def get(self, url, *, allow_redirects, timeout, content_callback):
                assert not allow_redirects
                seen.append({"url": url, "timeout": timeout, "limit": self.options["curl_options"][resources.CurlOpt.MAXFILESIZE_LARGE]})
                action = next(actions)
                if callable(action):
                    action = await action()
                if isinstance(action, Exception):
                    raise action
                for start in range(0, len(action.body), 65536):
                    chunk = action.body[start:start + 65536]
                    if content_callback(chunk) == resources.CURL_WRITEFUNC_ERROR:
                        raise RequestException("untrusted transport detail", code=resources.CurlECode.RECV_ERROR)
                return action

        return Session

    async def test_complete_html_over_one_megabyte_keeps_later_real_image(self):
        payload = b"<!--" + b"x" * (1024 * 1024 + 100) + b"-->" + html(image="https://images.example/gameplay.png")
        seen = []
        self.assertEqual(resources.PAGE_BYTES, 4 * 1024 * 1024)
        self.assertEqual(resources.IMAGE_BYTES, 8 * 1024 * 1024)
        with patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session([self.response(payload)], seen)):
            result = await resources.fetch_poster_resource(SOURCE)
        self.assertEqual(result.body, payload)
        self.assertEqual(page_images(SOURCE, result.body, "free-world", project_repo=REPO)["images"][0]["url"],
                         "https://images.example/gameplay.png")
        self.assertEqual(seen[0]["limit"], 4 * 1024 * 1024)
        self.assertLessEqual(seen[0]["timeout"], 12)

    async def test_exact_limit_is_complete_but_stream_and_declared_overflow_reject(self):
        for payload_size, succeeds in ((resources.PAGE_BYTES, True), (resources.PAGE_BYTES + 1, False)):
            seen = []
            payload = b"x" * payload_size
            with self.subTest(size=payload_size), patch.object(resources, "pin_http_target", self.public), \
                    patch.object(resources, "AsyncSession", self.session([self.response(payload)], seen)):
                if succeeds:
                    self.assertEqual((await resources.fetch_poster_resource(SOURCE)).body, payload)
                else:
                    with self.assertRaisesRegex(resources.PosterResourceError, "^page_too_large$"):
                        await resources.fetch_poster_resource(SOURCE)
            self.assertEqual(sum("url" in event for event in seen), 1)
            self.assertTrue(seen[-1]["closed"])
        seen = []
        overflow = RequestException("untrusted content length", code=resources.CurlECode.FILESIZE_EXCEEDED)
        with patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session([overflow], seen)):
            with self.assertRaisesRegex(resources.PosterResourceError, "^page_too_large$"):
                await resources.fetch_poster_resource(SOURCE)
        self.assertEqual(sum("url" in event for event in seen), 1)

    async def test_redirect_transfer_bytes_do_not_reset_the_page_budget(self):
        seen = []
        first = self.response(b"x" * (2 * 1024 * 1024), status=302, location=CHILD)
        second = self.response(b"x" * (2 * 1024 * 1024 + 1))
        with patch.object(resources, "pin_http_target", side_effect=self.public) as pin, \
                patch.object(resources, "AsyncSession", self.session([first, second], seen)):
            with self.assertRaisesRegex(resources.PosterResourceError, "^page_too_large$"):
                await resources.fetch_poster_resource(SOURCE)
        requests = [event for event in seen if "url" in event]
        self.assertEqual([event["limit"] for event in requests], [4 * 1024 * 1024, 2 * 1024 * 1024])
        self.assertEqual(pin.call_count, 2)
        self.assertTrue(all(call.kwargs["reject_mixed"] for call in pin.call_args_list))

    async def test_private_redirect_and_encoded_dot_path_never_open_target(self):
        for target in ("https://127.0.0.1/private", "https://github.com/author/free-world/tree/main/%2e%2e/private"):
            seen = []
            with self.subTest(target=target), patch.object(resources, "pin_http_target", self.public), \
                    patch.object(resources, "AsyncSession", self.session([self.response(status=302, location=target)], seen)):
                with self.assertRaises(resources.PosterResourceError):
                    await resources.fetch_poster_resource(SOURCE)
            self.assertEqual([event["url"] for event in seen if "url" in event], [SOURCE])

    async def test_cancellation_closes_page_session_and_does_not_retry(self):
        entered, seen = asyncio.Event(), []

        async def blocked():
            entered.set()
            await asyncio.Future()

        with patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session([blocked], seen)):
            task = asyncio.create_task(resources.fetch_poster_resource(SOURCE))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
        self.assertEqual(sum("url" in event for event in seen), 1)
        self.assertTrue(seen[-1]["closed"])

    async def test_html_page_with_image_filename_is_not_an_image(self):
        seen = []
        with patch.object(resources, "pin_http_target", self.public), \
                patch.object(resources, "AsyncSession", self.session([self.response(html(image=RAW))], seen)):
            with self.assertRaisesRegex(resources.PosterResourceError, "^invalid_image$"):
                await resources.fetch_poster_resource(DETAIL, image=True)
        self.assertEqual(sum("url" in event for event in seen), 1)


class MediaDepthTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_dom_hops_reach_blob_then_only_its_actual_image(self):
        model = model_with(tool("search_web", {"query": "free-world author screenshots", "identityKind": "project"}),
                           *(tool("read_page", {"resultId": f"page-{i}"}) for i in range(1, 4)),
                           tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
                           AIMessage(content='{"candidateId":"image-1"}'))
        fetch = AsyncMock(side_effect=[resources.PosterResource(SOURCE, html(CHILD), "text/html"),
                                      resources.PosterResource(CHILD, html(DETAIL), "text/html"),
                                      resources.PosterResource(DETAIL, html(DETAIL.replace("gameplay.png", "other.png"), image=RAW), "text/html"),
                                      resources.PosterResource(RAW, b"image", "image/png")])
        review = AsyncMock(return_value={"matches": True, "kind": "screenshot", "reason": "matched"})
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}), fetch=fetch,
                                review=review, cache=AsyncMock(return_value=cached_image()))
        result = await agent.run({"repo": REPO, "detailsVersion": 1, "gameNameOriginal": ""})
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual([call.args[0] for call in fetch.await_args_list], [SOURCE, CHILD, DETAIL, RAW])
        reads = [event for event in result["posterTrace"] if event.get("tool") == "read_page"]
        self.assertEqual([event["linkDepth"] for event in reads], [0, 1, 2])
        self.assertEqual([event["candidateIds"] for event in reads], [[], [], ["image-1"]])
        self.assertEqual(reads[-1]["linkedResults"], [])
        self.assertEqual(agent.counts, {"search_web": 1, "read_page": 3, "verify_image": 1})
        self.assertEqual(agent.limits, {"search_web": 2, "read_page": 6, "verify_image": 3})
        self.assertEqual(agent.deadline_seconds, 180)
        review.assert_awaited_once()

    async def test_third_hop_and_loop_do_not_add_more_pages(self):
        too_deep = CHILD + "/deeper"
        model = model_with(tool("search_web", {"query": "free-world author screenshots", "identityKind": "project"}),
                           *(tool("read_page", {"resultId": f"page-{i}"}) for i in range(1, 4)),
                           *[AIMessage(content='{"candidateId":""}') for _ in range(3)])
        fetch = AsyncMock(side_effect=[resources.PosterResource(SOURCE, html(CHILD, SOURCE), "text/html"),
                                      resources.PosterResource(CHILD, html(too_deep, SOURCE), "text/html"),
                                      resources.PosterResource(too_deep, html(too_deep.replace("/tree/", "/blob/") + "/image.png", CHILD), "text/html")])
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": SOURCE}]}), fetch=fetch)
        result = await agent.run({"repo": REPO, "detailsVersion": 1, "gameNameOriginal": ""})
        self.assertNotEqual(result["posterStatus"], "ready")
        self.assertEqual(fetch.await_count, 3)
        self.assertEqual(len(agent.results), 3)
        self.assertEqual([event for event in result["posterTrace"] if event.get("tool") == "read_page"][-1]["linkedResults"], [])

    def test_extra_hop_requires_exact_repo_ref_and_downward_media_path(self):
        self.assertTrue(project_media_directory(SOURCE, REPO))
        self.assertTrue(project_media_descendant(SOURCE, CHILD, REPO))
        self.assertTrue(project_media_descendant(CHILD, DETAIL, REPO))
        invalid = [DETAIL.replace("/main/", "/develop/"), DETAIL.replace("author/free-world", "someone/free-world"),
                   DETAIL.replace("author/free-world", "author/free-world-2"), DETAIL.replace("github.com", "github.com.evil.example"),
                   DETAIL.replace("/main/", "/main%2Fother/"), DETAIL.replace("/screenshots/", "/screenshots/%2e%2e/"),
                   DETAIL.replace(".png", ".svg"), DETAIL.replace(".png", ".html"), RAW, SOURCE, CHILD,
                   CHILD + "/%252e%252e/image.png", "https://127.0.0.1/screenshots/image.png"]
        for target in invalid:
            with self.subTest(target=target):
                self.assertFalse(project_media_descendant(CHILD, target, REPO))
                parsed = page_images(CHILD, html(target), "free-world", project_repo=REPO)
                self.assertEqual(parsed["images"], [])
                self.assertEqual(parsed["links"], [])
        self.assertFalse(project_media_descendant(SOURCE.replace("screenshots", "src"), DETAIL.replace("screenshots", "src"), REPO))
        self.assertFalse(project_media_descendant(DETAIL, DETAIL + "/more.png", REPO))

    def test_first_discovery_depth_is_stable_when_linked_or_searched_again(self):
        agent = GamePosterAgent(None)
        identity = {"identityKind": "project", "identityName": "free-world", "identityRepo": REPO}
        root = agent._register_result({"url": SOURCE, **identity})
        same = agent._register_result({"url": SOURCE, "parentResultId": "page-previous", "linkDepth": 1, **identity})
        self.assertEqual(root["linkDepth"], 0)
        self.assertEqual(same["linkDepth"], 0)
        child = agent._register_result({"url": CHILD, "parentResultId": root["resultId"], "linkDepth": 1, **identity})
        searched = agent._register_result({"url": CHILD, **identity})
        self.assertEqual(child["linkDepth"], 1)
        self.assertEqual(searched["linkDepth"], 1)
        self.assertEqual(agent.results[child["resultId"]]["linkDepth"], 1)

    async def test_direct_search_page_keeps_first_hop_after_another_page_links_it(self):
        first = "https://games.example/free-world"
        direct = first + "/images"
        gallery = direct + "/gallery"
        later = gallery + "/more"
        model = model_with(tool("search_web", {"query": "Free World cover"}),
                           *(tool("read_page", {"resultId": f"page-{i}"}) for i in range(1, 4)),
                           *[AIMessage(content='{"candidateId":""}') for _ in range(3)])
        fetch = AsyncMock(side_effect=[resources.PosterResource(first, html(direct), "text/html"),
                                      resources.PosterResource(direct, html(gallery), "text/html"),
                                      resources.PosterResource(gallery, html(later), "text/html")])
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": first}, {"url": direct}]}), fetch=fetch)
        result = await agent.run({"repo": REPO, "detailsVersion": 1, "gameNameOriginal": "Free World"})
        reads = [event for event in result["posterTrace"] if event.get("tool") == "read_page"]
        self.assertEqual([call.args[0] for call in fetch.await_args_list], [first, direct, gallery])
        self.assertEqual(reads[1]["parentResultId"], "page-1")  # Provenance is not depth.
        self.assertEqual([event["linkDepth"] for event in reads], [0, 0, 1])
        self.assertEqual([link["url"] for link in reads[1]["linkedResults"]], [gallery])
        self.assertEqual(reads[2]["linkedResults"], [])
        self.assertEqual(len(agent.results), 3)
        self.assertEqual(agent.counts["read_page"], 3)
