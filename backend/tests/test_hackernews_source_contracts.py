from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services.ingestion import source_hackernews
from backend.app.services.ingestion.crawlers import hackernews_crawler


class _JsonResponse:
    def __init__(self, value) -> None:
        self._value = value

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._value


class _AsyncClient:
    def __init__(self, responses) -> None:
        self._responses = list(responses)
        self.get = AsyncMock(side_effect=self._responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class HackerNewsSourceContracts(unittest.IsolatedAsyncioTestCase):
    async def test_two_client_lifecycle_filter_sort_and_exact_projection(self) -> None:
        now_ts = 1_800_000_000.0
        top_client = _AsyncClient([_JsonResponse([101, 102, 103, 104] + list(range(200, 240)))])
        detail_client = _AsyncClient(
            [
                _JsonResponse(
                    {
                        "id": 101,
                        "type": "story",
                        "title": "Lower score",
                        "score": 10,
                        "descendants": 2,
                        "time": now_ts - 3600,
                        "by": "alice",
                    }
                ),
                _JsonResponse(
                    {
                        "id": 102,
                        "type": "story",
                        "title": "Higher score",
                        "url": "https://example.test/high",
                        "score": 50,
                        "descendants": 7,
                        "time": now_ts - 86400,
                        "by": "bob",
                    }
                ),
                _JsonResponse(
                    {
                        "id": 103,
                        "type": "story",
                        "title": "Too old",
                        "score": 100,
                        "time": now_ts - 86401,
                    }
                ),
                _JsonResponse(
                    {
                        "id": 104,
                        "type": "comment",
                        "title": "Not a story",
                        "score": 999,
                        "time": now_ts,
                    }
                ),
            ]
            + [_JsonResponse(None) for _ in range(26)]
        )

        with (
            patch.object(source_hackernews.time, "time", return_value=now_ts),
            patch.object(
                source_hackernews.httpx,
                "AsyncClient",
                side_effect=[top_client, detail_client],
            ) as client_type,
        ):
            results = await source_hackernews.fetch_hackernews_items_async(limit=10)

        self.assertEqual(client_type.call_count, 2)
        self.assertEqual(
            client_type.call_args_list[0].kwargs,
            {"timeout": 15, "trust_env": True, "follow_redirects": True},
        )
        self.assertEqual(
            client_type.call_args_list[1].kwargs,
            {"timeout": 10, "trust_env": True, "follow_redirects": True},
        )
        top_client.get.assert_awaited_once_with(source_hackernews._HN_TOP_STORIES_URL)
        self.assertEqual(detail_client.get.await_count, 30)
        self.assertEqual([item["hn_id"] for item in results], ["102", "101"])
        self.assertEqual([item["rank_in_period"] for item in results], [1, 2])
        self.assertEqual(
            results[0],
            {
                "title": "Higher score",
                "url": "https://example.test/high",
                "abstract": "Higher score",
                "summary": "Higher score",
                "source": "hackernews",
                "source_channel": "hn_daily_html",
                "channel": "hn_daily_html",
                "score": 50.0,
                "raw_score": 50.0,
                "votes": 50,
                "comments": 7,
                "published_date": "2027-01-14",
                "hn_id": "102",
                "author": "bob",
                "rank_in_period": 1,
                "tags": ["hackernews", "daily", "top30"],
            },
        )
        self.assertEqual(
            results[1]["url"],
            "https://news.ycombinator.com/item?id=101",
        )

    async def test_topstories_failure_and_invalid_payload_return_empty(self) -> None:
        failing_client = _AsyncClient([])
        failing_client.get.side_effect = RuntimeError("offline")
        with patch.object(
            source_hackernews.httpx,
            "AsyncClient",
            return_value=failing_client,
        ):
            self.assertEqual(
                await source_hackernews.fetch_hackernews_items_async(),
                [],
            )

        invalid_client = _AsyncClient([_JsonResponse({"not": "a list"})])
        with patch.object(
            source_hackernews.httpx,
            "AsyncClient",
            return_value=invalid_client,
        ):
            self.assertEqual(
                await source_hackernews.fetch_hackernews_items_async(),
                [],
            )

    async def test_item_failures_dead_and_deleted_entries_are_partial_not_fatal(self) -> None:
        top_client = _AsyncClient([_JsonResponse([1, 2, 3])])
        detail_client = _AsyncClient(
            [
                RuntimeError("item unavailable"),
                _JsonResponse({"id": 2, "type": "story", "dead": True}),
                _JsonResponse({"id": 3, "type": "story", "deleted": True}),
            ]
        )
        with patch.object(
            source_hackernews.httpx,
            "AsyncClient",
            side_effect=[top_client, detail_client],
        ):
            results = await source_hackernews.fetch_hackernews_items_async()

        self.assertEqual(results, [])


class HackerNewsSyncWrapperContracts(unittest.TestCase):
    def test_sync_wrapper_forwards_compatibility_arguments_without_active_loop(self) -> None:
        captured = {}

        async def fake_fetch(**kwargs):
            captured.update(kwargs)
            return [{"title": "Example"}]

        with patch.object(
            source_hackernews,
            "fetch_hackernews_items_async",
            side_effect=fake_fetch,
        ):
            result = source_hackernews.fetch_hackernews_items(
                limit=7,
                period="weekly",
                target_date="2026-07-28",
                use_llm_filter=True,
            )

        self.assertEqual(result, [{"title": "Example"}])
        self.assertEqual(
            captured,
            {
                "limit": 7,
                "period": "weekly",
                "target_date": "2026-07-28",
                "use_llm_filter": True,
            },
        )


class HackerNewsActiveLoopContracts(unittest.IsolatedAsyncioTestCase):
    async def test_sync_wrapper_uses_thread_compatibility_inside_active_loop(self) -> None:
        async def fake_fetch(**kwargs):
            return [kwargs]

        with patch.object(
            source_hackernews,
            "fetch_hackernews_items_async",
            side_effect=fake_fetch,
        ):
            result = source_hackernews.fetch_hackernews_items(limit=4)

        self.assertEqual(result[0]["limit"], 4)
        self.assertEqual(result[0]["period"], "daily")


class HackerNewsCrawlerContracts(unittest.IsolatedAsyncioTestCase):
    async def test_crawler_forces_daily_and_uses_physical_cst_snapshot(self) -> None:
        items = [{"title": "Example"}]
        with (
            patch.object(hackernews_crawler, "today_cst", return_value="2026-07-28"),
            patch.object(
                hackernews_crawler,
                "fetch_hackernews_items_async",
                new=AsyncMock(return_value=items),
            ) as fetch,
        ):
            result = await hackernews_crawler.HackerNewsCrawler()._do_fetch(
                period="weekly",
                limit=9,
                target_date="2020-01-01",
            )

        fetch.assert_awaited_once_with(limit=9, period="daily")
        self.assertEqual(result.period, "daily")
        self.assertEqual(result.snapshot_date, "2026-07-28")
        self.assertEqual(result.source_channel, "hn_daily_html")
        self.assertEqual(items[0]["source"], "hackernews")
        self.assertEqual(items[0]["channel"], "hn_daily_html")


if __name__ == "__main__":
    unittest.main()
