"""DailyHot 聚合热榜源：解析、爬虫包装与管线注册契约测试。"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import patch

from backend.app.core.scheduler import _BRIEFING_TASKS
from backend.app.core.scheduler_registry import (
    SOURCE_JOB_DESCRIPTORS,
)
from backend.app.services.briefing.daily_briefing import (
    _PERIOD_CHANNEL_MAP,
    _SOURCE_CONFIG,
    _filter_docs_by_period,
)
from backend.app.services.ingestion.content_enricher import _ENRICH_MAP
from backend.app.services.ingestion.crawlers.dailyhot_crawler import DailyHotCrawler
from backend.app.services.ingestion.source_dailyhot import (
    SOURCE_CHANNEL,
    _normalise_item,
    fetch_dailyhot_items,
    parse_endpoint_list,
)


def _endpoint_payload(items: list[dict[str, Any]], *, code: int = 200) -> dict[str, Any]:
    return {
        "code": code,
        "name": "ithome",
        "title": "IT之家",
        "type": "热榜",
        "total": len(items),
        "data": items,
    }


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    """按 URL 尾段路由到预置 payload 的 httpx.AsyncClient 替身。"""

    def __init__(self, payloads: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        self._payloads = payloads

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def get(self, url: str) -> _FakeResponse:
        endpoint = url.rstrip("/").rsplit("/", 1)[-1]
        payload = self._payloads[endpoint]
        if isinstance(payload, Exception):
            raise payload
        return _FakeResponse(payload)


class ParseEndpointListTests(unittest.TestCase):
    def test_parses_dedupes_and_preserves_order(self) -> None:
        self.assertEqual(
            parse_endpoint_list(" 36kr, ithome ,36kr,,zhihu "),
            ["36kr", "ithome", "zhihu"],
        )

    def test_empty_yields_empty(self) -> None:
        self.assertEqual(parse_endpoint_list(" , ,"), [])


class NormaliseItemTests(unittest.TestCase):
    def test_missing_title_or_url_is_dropped(self) -> None:
        self.assertIsNone(
            _normalise_item(
                {"title": "", "url": "https://x"},
                endpoint="ithome",
                feed_title="IT之家热榜",
                rank=1,
            )
        )
        self.assertIsNone(
            _normalise_item(
                {"title": "有标题", "url": ""},
                endpoint="ithome",
                feed_title="IT之家热榜",
                rank=1,
            )
        )

    def test_millisecond_timestamp_converted_to_cst_date(self) -> None:
        item = _normalise_item(
            {
                "title": "某 AI 发布会",
                "url": "https://example.com/1",
                "hot": 123456,
                # 2026-08-05 00:00:00 UTC+8 的毫秒时间戳
                "timestamp": 1785859200000,
            },
            endpoint="ithome",
            feed_title="IT之家热榜",
            rank=2,
        )
        assert item is not None
        self.assertEqual(item["published_date"], "2026-08-05")
        self.assertEqual(item["raw_score"], 123456.0)
        # 端点内名次归一：rank=2 → 99 分
        self.assertEqual(item["score"], 99.0)
        self.assertEqual(item["source"], "dailyhot")
        self.assertEqual(item["source_channel"], SOURCE_CHANNEL)

    def test_invalid_hot_and_timestamp_fall_back_to_zero(self) -> None:
        item = _normalise_item(
            {"title": "t", "url": "https://example.com/2", "hot": "abc",
             "timestamp": "not-a-number"},
            endpoint="ithome",
            feed_title="IT之家热榜",
            rank=1,
        )
        assert item is not None
        self.assertEqual(item["raw_score"], 0.0)
        self.assertEqual(item["published_date"], "")


class FetchDailyHotItemsTests(unittest.TestCase):
    def test_aggregates_per_endpoint_top_n_and_reranks(self) -> None:
        payloads = {
            "ithome": _endpoint_payload(
                [
                    {"title": f"IT 热{i}", "url": f"https://it/{i}", "hot": 100 - i}
                    for i in range(8)
                ]
            ),
            "zhihu": _endpoint_payload(
                [
                    {"title": f"知乎热{i}", "url": f"https://zh/{i}", "hot": 999 - i}
                    for i in range(3)
                ]
            ),
        }
        with patch(
            "backend.app.services.ingestion.source_dailyhot.httpx.AsyncClient",
            lambda *a, **kw: _FakeAsyncClient(payloads, *a, **kw),
        ):
            items = asyncio.run(
                fetch_dailyhot_items(
                    base_url="http://dailyhot:6688",
                    endpoints=["ithome", "zhihu"],
                    per_endpoint_limit=5,
                )
            )

        # 8 → 截断 5，3 全留，共 8 条
        self.assertEqual(len(items), 8)
        # 交错排序：两榜 rank1 在前（按端点名排序），随后 rank2...
        self.assertEqual(
            [(item["endpoint"], item["title"]) for item in items[:3]],
            [("ithome", "IT 热0"), ("zhihu", "知乎热0"), ("ithome", "IT 热1")],
        )
        # rank_in_period 已按合并结果重排为 1..8
        self.assertEqual([item["rank_in_period"] for item in items], list(range(1, 9)))

    def test_endpoint_failure_and_non_200_are_isolated(self) -> None:
        payloads = {
            "ithome": ConnectionError("connection refused"),
            "weibo": _endpoint_payload([], code=500),
            "zhihu": _endpoint_payload(
                [{"title": "幸存", "url": "https://zh/1", "hot": 10}]
            ),
        }
        with patch(
            "backend.app.services.ingestion.source_dailyhot.httpx.AsyncClient",
            lambda *a, **kw: _FakeAsyncClient(payloads, *a, **kw),
        ):
            items = asyncio.run(
                fetch_dailyhot_items(
                    base_url="http://dailyhot:6688",
                    endpoints=["ithome", "weibo", "zhihu"],
                    per_endpoint_limit=5,
                )
            )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "幸存")

    def test_no_endpoints_yields_empty(self) -> None:
        self.assertEqual(
            asyncio.run(fetch_dailyhot_items(base_url="http://x", endpoints=[])),
            [],
        )


class DailyHotCrawlerWrapperTests(unittest.TestCase):
    def test_wrapper_contract(self) -> None:
        crawler = DailyHotCrawler(
            base_url="http://dailyhot:6688",
            endpoints=["ithome"],
            per_endpoint_limit=3,
        )
        self.assertEqual(crawler.source_name, "dailyhot")
        self.assertEqual(crawler.supported_periods, ["daily"])

        payloads = {
            "ithome": _endpoint_payload(
                [{"title": "A", "url": "https://it/1", "hot": 5}]
            )
        }
        with patch(
            "backend.app.services.ingestion.source_dailyhot.httpx.AsyncClient",
            lambda *a, **kw: _FakeAsyncClient(payloads, *a, **kw),
        ):
            result = asyncio.run(crawler.fetch(period="daily", limit=25))

        self.assertTrue(result.ok)
        self.assertEqual(result.source, "dailyhot")
        self.assertEqual(result.source_channel, "dailyhot_daily")
        self.assertEqual(result.period, "daily")
        self.assertEqual(len(result.items), 1)
        self.assertRegex(result.snapshot_date, r"^\d{4}-\d{2}-\d{2}$")

    def test_upstream_down_yields_empty_result_not_exception(self) -> None:
        crawler = DailyHotCrawler(base_url="http://dailyhot:6688", endpoints=["ithome"])
        payloads = {"ithome": ConnectionError("connection refused")}
        with patch(
            "backend.app.services.ingestion.source_dailyhot.httpx.AsyncClient",
            lambda *a, **kw: _FakeAsyncClient(payloads, *a, **kw),
        ):
            result = asyncio.run(crawler.fetch(period="daily", limit=25))
        # 端点级错误被隔离为空列表：整体 ok 但无数据，绝不抛出。
        self.assertTrue(result.ok)
        self.assertEqual(result.items, [])


class PipelineRegistrationTests(unittest.TestCase):
    def test_scheduler_descriptor_registered(self) -> None:
        by_id = {descriptor.id: descriptor for descriptor in SOURCE_JOB_DESCRIPTORS}
        descriptor = by_id["dailyhot_hotlists"]
        self.assertEqual(descriptor.source, "dailyhot")
        self.assertEqual(descriptor.schedule.minute, 7)

    def test_composition_includes_dailyhot_factory(self) -> None:
        from unittest.mock import MagicMock

        from backend.app.services.ingestion.composition import (
            provide_ingestion_dependencies,
        )

        dependencies = provide_ingestion_dependencies(repositories=MagicMock())
        from backend.app.services.ingestion.crawlers import DailyHotCrawler

        self.assertIn(DailyHotCrawler, dependencies.crawler_factories)

    def test_enrich_map_covers_dailyhot(self) -> None:
        self.assertIn("dailyhot", _ENRICH_MAP)

    def test_briefing_source_config_and_channel_map(self) -> None:
        self.assertIn("dailyhot", _SOURCE_CONFIG)
        prompt, suffix = _SOURCE_CONFIG["dailyhot"]
        self.assertEqual(suffix, "_dailyhot")
        self.assertIn("dailyhot", prompt)  # 标签要求
        self.assertEqual(_PERIOD_CHANNEL_MAP["dailyhot"], {"daily": "dailyhot_daily"})

    def test_filter_docs_by_period_keeps_dailyhot_daily(self) -> None:
        docs = [
            {"source": "dailyhot", "source_channel": "dailyhot_daily", "title": "A"},
            {"source": "dailyhot", "source_channel": "other", "title": "B"},
        ]
        filtered = _filter_docs_by_period(docs, "dailyhot", "daily")
        self.assertEqual([doc["title"] for doc in filtered], ["A"])

    def test_briefing_tasks_include_dailyhot(self) -> None:
        self.assertIn({"source": "dailyhot", "period": "daily"}, _BRIEFING_TASKS)

    def test_subscription_and_report_vocabularies_include_dailyhot(self) -> None:
        from typing import get_args

        from backend.app.api.routes_report import _VALID_SOURCES
        from backend.app.models.schema_push import SubscriptionSource
        from backend.app.services.email.message_renderer import SOURCE_LABELS

        self.assertIn("dailyhot", get_args(SubscriptionSource))
        self.assertIn("dailyhot", _VALID_SOURCES)
        self.assertEqual(SOURCE_LABELS["dailyhot"], "全网热榜报告")

    def test_mcp_source_choice_deliberately_unchanged(self) -> None:
        # MCP wire 枚举属 Red 变更，本单元刻意不扩展（随 B 路线单独评估）。
        from typing import get_args

        from backend.app.services.mcp.contracts import SourceChoice

        self.assertNotIn("dailyhot", get_args(SourceChoice))


if __name__ == "__main__":
    unittest.main()
