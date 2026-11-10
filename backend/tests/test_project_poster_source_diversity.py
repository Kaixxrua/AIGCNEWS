from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, ToolMessage

from backend.app.services.outbound_target_policy import pin_http_target
from backend.app.services.project_catalog import game_poster_resources as resources
from backend.app.services.project_catalog.game_poster_agent import GamePosterAgent, page_images
from backend.app.services.project_catalog.game_poster_page_identity import project_image_detail
from backend.app.services.project_catalog.game_poster_resources import PosterResource, PosterResourceError
from backend.tests.test_project_poster_coverage import cached_image
from backend.tests.test_project_web_posters import IMAGE, ITEM, ORIGINAL, model_with, tool

BAD = "https://unavailable.example/game/"
GOOD = "https://another.example/game/"


def read_many(*identifiers):
    return AIMessage(content="", tool_calls=[
        {"name": "read_page", "args": {"resultId": identifier}, "id": identifier, "type": "tool_call"}
        for identifier in identifiers
    ])


class SourceDiversityTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_denied_pages_preserve_budget_for_another_real_source(self):
        model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}),
                           read_many("page-1", "page-2", "page-3", "page-4", "page-5"),
                           tool("read_page", {"resultId": "page-3"}),
                           tool("read_page", {"resultId": "page-6"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
                           AIMessage(content='{"candidateId":"image-1"}'))

        async def fetch(url, *, image=False):
            if url.startswith(BAD):
                raise PosterResourceError("page_unavailable", http_status=403)
            return (PosterResource(IMAGE, b"image", "image/jpeg") if image else
                    PosterResource(url, f'<h1>{ORIGINAL}</h1><img src="{IMAGE}">'.encode(), "text/html"))

        fetch = AsyncMock(side_effect=fetch)
        search = AsyncMock(return_value={"results": [{"url": BAD + str(i)} for i in range(5)] + [{"url": GOOD}]})
        agent = GamePosterAgent(model, search=search, fetch=fetch, cache=AsyncMock(return_value=cached_image()))
        result = await agent.run(ITEM)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(sum(call.args[0].startswith(BAD) for call in fetch.await_args_list), 2)
        self.assertEqual(agent.counts, {"search_web": 1, "read_page": 3, "verify_image": 1})
        self.assertEqual(agent.limits, {"search_web": 2, "read_page": 6, "verify_image": 3})
        failures = [row for row in result["posterTrace"] if row.get("error")]
        self.assertEqual([row.get("httpStatus") for row in failures[:2]], [403, 403])
        self.assertEqual(sum(row["error"] == "page_source_in_flight" for row in failures), 3)
        self.assertEqual(failures[-1]["error"], "page_source_unavailable")
        messages = [json.loads(message.content) for message in model.ainvoke.call_args.args[0] if isinstance(message, ToolMessage)]
        blocked = next(message for message in messages if message.get("error") == "page_source_unavailable")
        self.assertEqual(blocked["unreadSources"][0]["url"], GOOD)
        self.assertFalse(agent.pending_page_hosts)

    async def test_missing_paths_and_unknown_legacy_errors_do_not_block_a_host(self):
        for status in (404, 410, None):
            with self.subTest(status=status):
                model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}),
                                   tool("read_page", {"resultId": "page-1"}),
                                   tool("read_page", {"resultId": "page-2"}),
                                   tool("read_page", {"resultId": "page-3"}),
                                   tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
                                   AIMessage(content='{"candidateId":"image-1"}'))
                fetch = AsyncMock(side_effect=[PosterResourceError("page_unavailable", http_status=status)] * 2 + [
                    PosterResource(BAD + "2", f'<h1>{ORIGINAL}</h1><img src="{IMAGE}">'.encode(), "text/html"),
                    PosterResource(IMAGE, b"image", "image/png"),
                ])
                agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": BAD + str(i)} for i in range(3)]}),
                                        fetch=fetch, cache=AsyncMock(return_value=cached_image()))
                result = await agent.run(ITEM)
                self.assertEqual(result["posterStatus"], "ready")
                self.assertEqual(agent.counts["read_page"], 3)
                self.assertEqual(agent.page_host_failures["unavailable.example"], 0)

    async def test_duplicate_result_cannot_release_another_calls_probe_reservation(self):
        model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}),
                           read_many("page-1", "page-1", "page-2", "page-3", "page-4"),
                           tool("read_page", {"resultId": "page-3"}),
                           AIMessage(content='{"candidateId":""}'), AIMessage(content='{"candidateId":""}'))
        fetch = AsyncMock(side_effect=PosterResourceError("page_unavailable", http_status=403))
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": BAD + str(i)} for i in range(4)]}), fetch=fetch)
        result = await agent.run(ITEM)
        self.assertNotEqual(result["posterStatus"], "ready")
        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(agent.counts["read_page"], 2)
        self.assertEqual(agent.page_host_failures["unavailable.example"], 2)
        self.assertEqual([row.get("error") for row in result["posterTrace"][1:7]],
                         ["page_unavailable", "page_already_read", "page_unavailable", "page_source_in_flight", "page_source_in_flight", "page_source_unavailable"])
        self.assertFalse(agent.pending_page_hosts)

    async def test_success_between_failures_resets_host_failure_streak(self):
        model = model_with(tool("search_web", {"query": ORIGINAL + " cover"}),
                           *(tool("read_page", {"resultId": f"page-{i}"}) for i in range(1, 5)),
                           tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
                           AIMessage(content='{"candidateId":"image-1"}'))
        fetch = AsyncMock(side_effect=[PosterResourceError("network_unavailable"),
            PosterResource(BAD + "1", f"<h1>{ORIGINAL}</h1>".encode(), "text/html"),
            PosterResourceError("page_unavailable", http_status=503),
            PosterResource(BAD + "3", f'<h1>{ORIGINAL}</h1><img src="{IMAGE}">'.encode(), "text/html"),
            PosterResource(IMAGE, b"image", "image/png")])
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": BAD + str(i)} for i in range(4)]}),
                                fetch=fetch, cache=AsyncMock(return_value=cached_image()))
        self.assertEqual((await agent.run(ITEM))["posterStatus"], "ready")
        self.assertEqual(agent.counts["read_page"], 4)
        self.assertEqual(agent.page_host_failures["unavailable.example"], 0)

    async def test_a_new_job_can_read_a_source_that_failed_in_an_earlier_job(self):
        search = AsyncMock(return_value={"results": [{"url": BAD + str(i)} for i in range(2)]})
        failed = GamePosterAgent(model_with(tool("search_web", {"query": ORIGINAL + " cover"}),
                                           read_many("page-1", "page-2"),
                                           AIMessage(content='{"candidateId":""}'), AIMessage(content='{"candidateId":""}')),
                                 search=search, fetch=AsyncMock(side_effect=PosterResourceError("network_unavailable")))
        await failed.run(ITEM)
        self.assertEqual(failed.page_host_failures["unavailable.example"], 2)
        current = GamePosterAgent(model_with(tool("search_web", {"query": ORIGINAL + " cover"}),
                                            tool("read_page", {"resultId": "page-1"}),
                                            tool("verify_image", {"candidateId": "image-1", "kind": "cover"}),
                                            AIMessage(content='{"candidateId":"image-1"}')),
                                  search=search, fetch=AsyncMock(side_effect=[
                                      PosterResource(BAD + "0", f'<h1>{ORIGINAL}</h1><img src="{IMAGE}">'.encode(), "text/html"),
                                      PosterResource(IMAGE, b"image", "image/jpeg")]),
                                  cache=AsyncMock(return_value=cached_image()))
        self.assertEqual((await current.run(ITEM))["posterStatus"], "ready")
        self.assertEqual(current.counts["read_page"], 1)

    def test_only_verified_host_failures_affect_the_source_circuit(self):
        for error, status, expected in [("network_unavailable", None, 1), ("tool_timeout", None, 1),
                                         ("page_unavailable", 403, 1), ("page_unavailable", 429, 1),
                                         ("page_unavailable", 500, 1), ("page_unavailable", 599, 1),
                                         ("page_unavailable", 404, 0), ("page_unavailable", 410, 0),
                                         ("page_unavailable", None, 0), ("page_unavailable", 200, 0)]:
            with self.subTest(error=error, status=status):
                agent = GamePosterAgent(None)
                record = {"resultId": "page-1", "error": error, "httpStatus": status}
                agent.pending_page_hosts[id(record)] = "example.com"
                agent._page_read_outcome(record)
                self.assertEqual(agent.page_host_failures["example.com"], expected)


class SafeStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_preserves_only_a_numeric_http_status(self):
        for status in (403, 404, 429, 503):
            class Session:
                def __init__(self, **kwargs):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_):
                    pass

                async def get(self, url, **kwargs):
                    kwargs["content_callback"](b"untrusted error body")
                    return SimpleNamespace(status_code=status, headers={"content-type": "text/html"})

            with self.subTest(status=status), patch.object(resources, "AsyncSession", Session), \
                    patch.object(resources, "pin_http_target", side_effect=lambda url, **kwargs: pin_http_target(url, resolver=lambda _: ["93.184.216.34"], **kwargs)):
                with self.assertRaisesRegex(PosterResourceError, "^page_unavailable$") as caught:
                    await resources.fetch_poster_resource(BAD)
                self.assertEqual(caught.exception.http_status, status)
        for invalid in (True, "403", 99, 600, None):
            self.assertIsNone(PosterResourceError("page_unavailable", http_status=invalid).http_status)


class RepositoryImageDetailTests(unittest.IsolatedAsyncioTestCase):
    async def test_directory_follows_actual_blob_page_then_actual_raw_image_once(self):
        repo = "author/free-world"
        source = "https://github.com/author/free-world/tree/main/screenshots"
        detail = "https://github.com/author/free-world/blob/main/screenshots/gameplay.png"
        raw = detail + "?raw=true"
        directory_html = f'<h1>Free World screenshots</h1><a href="{detail}">gameplay.png</a>'.encode()
        detail_html = f'<h1>Free World gameplay.png</h1><img src="{raw}" alt="Game screenshot"><a href="{detail.replace("gameplay.png", "other.png")}">other.png</a>'.encode()
        model = model_with(tool("search_web", {"query": "free-world author screenshots", "identityKind": "project"}),
                           tool("read_page", {"resultId": "page-1"}), tool("read_page", {"resultId": "page-2"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
                           AIMessage(content='{"candidateId":"image-1"}'))
        fetch = AsyncMock(side_effect=[PosterResource(source, directory_html, "text/html"),
                                      PosterResource(detail, detail_html, "text/html"), PosterResource(raw, b"image", "image/png")])
        review = AsyncMock(return_value={"matches": True, "kind": "screenshot", "reason": "matched"})
        agent = GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": source}]}), fetch=fetch,
                                review=review, cache=AsyncMock(return_value=cached_image()))
        result = await agent.run({"repo": repo, "detailsVersion": 1, "gameNameOriginal": ""})
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual([call.args[0] for call in fetch.await_args_list], [source, detail, raw])
        self.assertEqual(result["posterTrace"][1]["candidateIds"], [])
        self.assertEqual(result["posterTrace"][2]["parentResultId"], "page-1")
        self.assertEqual(result["posterTrace"][2]["linkedResults"], [])  # Still one hop.
        self.assertEqual(result["posterSourceUrl"], detail)
        self.assertEqual(agent.counts, {"search_web": 1, "read_page": 2, "verify_image": 1})
        review.assert_awaited_once()
        self.assertEqual(review.await_args.kwargs["candidate"]["identityKind"], "project")

    def test_cross_repo_unsafe_svg_and_raw_urls_are_not_detail_pages(self):
        repo = "author/free-world"
        good = "https://github.com/author/free-world/blob/main/screenshots/gameplay.png"
        self.assertTrue(project_image_detail(good, repo))
        addresses = [good.replace("author/free-world", "someone/free-world"),
                     good.replace("free-world/", "free-world-2/"), good.replace("github.com", "github.com.evil.example"),
                     good.replace("https:", "http:"), good.replace("github.com", "127.0.0.1"),
                     good.replace(".png", ".svg"), good + "?raw=true", good + "?raw=1", good.replace("/blob/", "/raw/"),
                     good.replace("/screenshots/", "/%2e%2e/")]
        for address in addresses:
            with self.subTest(address=address):
                self.assertFalse(project_image_detail(address, repo))
                page = page_images("https://github.com/author/free-world/tree/main/screenshots",
                                   f'<h1>Free World screenshots</h1><a href="{address}">gameplay.png</a>'.encode(),
                                   "free-world", project_repo=repo)
                self.assertEqual(page["images"], [])
                self.assertEqual(page["links"], [])

    def test_image_detail_links_share_existing_gallery_limit(self):
        body = '<h1>Free World screenshots</h1>' + ''.join(
            f'<a href="/author/free-world/blob/main/screenshots/{index}.png">screenshot {index}</a>' for index in range(8))
        page = page_images("https://github.com/author/free-world/tree/main/screenshots", body.encode(), "free-world", project_repo="author/free-world")
        self.assertEqual(len(page["links"]), 4)
        self.assertEqual(page["images"], [])
