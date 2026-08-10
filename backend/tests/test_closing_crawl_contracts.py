"""关榜采集契约（PR4a）：CST 源次日 00:3x 以昨日归属补采一轮。

覆盖：
  - ApplicationSchedulerRuntime 关榜方法：按调度时区计算昨日、透传
    target_date、关榜轮不接零入库告警、X 关榜持有 X 操作锁；
  - x/hackernews 爬虫：显式 target_date（关榜/回填）按指定日期归属，
    缺省仍归属当天 CST。
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from twitter_cli.models import Author, Metrics, Tweet

from backend.app.core import scheduler as scheduler_module
from backend.app.services.ingestion.crawlers import (
    hackernews_crawler as hn_crawler_module,
    x_crawler as x_crawler_module,
)


class _FrozenDateTime(datetime):
    """调度时区 2026-08-11 00:31：关榜窗口内，昨日 = 2026-08-10。"""

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        value = cls(2026, 8, 11, 0, 31, 0)
        return value.replace(tzinfo=tz) if tz else value


class ClosingJobWiringTests(unittest.IsolatedAsyncioTestCase):
    def _runtime(self) -> scheduler_module.ApplicationSchedulerRuntime:
        return scheduler_module.ApplicationSchedulerRuntime(
            MagicMock(),
            scheduler=MagicMock(running=False),
        )

    async def test_closing_jobs_target_yesterday_without_zero_ingest_alerts(
        self,
    ) -> None:
        runtime = self._runtime()
        calls: dict[str, dict[str, Any]] = {}

        async def fake_run(source_name: str, **kwargs: Any) -> bool:
            calls[source_name] = kwargs
            return True

        with (
            unittest.mock.patch.object(
                scheduler_module, "_run_single_source_job", fake_run
            ),
            unittest.mock.patch.object(
                scheduler_module, "datetime", _FrozenDateTime
            ),
        ):
            await runtime._run_x_closing_job()
            await runtime._run_hackernews_closing_job()
            await runtime._run_news_closing_job()

        assert set(calls) == {"x", "hackernews", "news"}
        for source_name, kwargs in calls.items():
            assert kwargs["target_date"] == "2026-08-10", source_name
            # 关榜轮零入库是常态（尾巴内容可能为空），不接零入库告警
            assert kwargs["zero_ingest_reporter"] is None, source_name
        # X 关榜仍持有 X 操作锁：与采集/测活串行，不并发请求 X
        assert calls["x"]["x_lock"] is runtime.x_operation_lock

    async def test_closing_failure_alerts_use_distinct_job_ids(self) -> None:
        runtime = self._runtime()

        async def failing_run(source_name: str, **kwargs: Any) -> bool:
            return False

        recorded: list[str] = []
        runtime._failure_alerter.record_failure = (  # type: ignore[method-assign]
            lambda job_id, detail="": recorded.append(job_id)
        )
        with unittest.mock.patch.object(
            scheduler_module, "_run_single_source_job", failing_run
        ):
            await runtime._run_x_closing_job()
            await runtime._run_hackernews_closing_job()

        assert recorded == ["source:x_closing", "source:hackernews_closing"]

    def test_job_callbacks_expose_closing_entries(self) -> None:
        runtime = self._runtime()
        callbacks = runtime._job_callbacks()
        for name in (
            "_run_x_closing_job",
            "_run_hackernews_closing_job",
            "_run_news_closing_job",
        ):
            assert callable(callbacks[name])


def _tweet(tweet_id: str, created_at: str) -> Tweet:
    tweet = Tweet(
        id=tweet_id,
        text="synthetic",
        author=Author(id="u1", name="OpenAI", screen_name="openai"),
        metrics=Metrics(
            likes=1,
            retweets=0,
            replies=0,
            quotes=0,
            views=10,
            bookmarks=0,
        ),
        created_at=created_at,
        is_retweet=False,
    )
    tweet.is_promoted = False
    tweet.is_subscriber_only = False
    return tweet


class _FakeXTransport:
    def __init__(self, tweets: list[Tweet]) -> None:
        self._tweets = tweets

    async def fetch_watchlist_tweets(
        self, handles: list[str], per_account: int
    ) -> dict[str, list[Tweet]]:
        return {handles[0]: self._tweets}


def _x_crawler(tweets: list[Tweet]) -> x_crawler_module.XCrawler:
    return x_crawler_module.XCrawler(
        transport=_FakeXTransport(tweets),  # type: ignore[arg-type]
        watchlist_provider=lambda: ["openai"],
        translation_fetcher=lambda ids: {},
    )


def test_x_crawler_explicit_target_date_attributes_and_filters_to_that_day() -> None:
    """关榜轮：target_date=D → 快照归属 D，且只收 CST D 当天推文。"""
    tweets = [
        # UTC 08-10 15:59:59 = CST 08-10 23:59:59（D 的尾巴，保留）
        _tweet("3001", "Mon Aug 10 15:59:59 +0000 2026"),
        # UTC 08-10 16:00 = CST 08-11 00:00（次日，剔除）
        _tweet("3002", "Mon Aug 10 16:00:00 +0000 2026"),
    ]
    result = asyncio.run(
        _x_crawler(tweets).fetch("daily", limit=10, target_date="2026-08-10")
    )

    assert result.ok
    assert result.snapshot_date == "2026-08-10"
    assert len(result.items) == 1
    assert "3001" in str(result.items[0])


def test_x_crawler_default_still_attributes_to_today_cst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(x_crawler_module, "today_cst", lambda: "2026-08-11")
    tweets = [_tweet("3001", "Mon Aug 10 15:59:59 +0000 2026")]
    result = asyncio.run(_x_crawler(tweets).fetch("daily", limit=10))

    assert result.snapshot_date == "2026-08-11"
    # 过滤跟随归属日：昨日推文不进今日切片
    assert result.items == []


def test_hackernews_crawler_explicit_target_date_and_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(**kwargs: Any) -> list[dict[str, Any]]:
        return [{"title": "Synthetic HN", "url": "https://example.com/1"}]

    monkeypatch.setattr(hn_crawler_module, "fetch_hackernews_items_async", fake_fetch)

    closing = asyncio.run(
        hn_crawler_module.HackerNewsCrawler().fetch(
            "daily", limit=30, target_date="2026-08-10"
        )
    )
    assert closing.snapshot_date == "2026-08-10"

    monkeypatch.setattr(hn_crawler_module, "today_cst", lambda: "2026-08-11")
    default = asyncio.run(hn_crawler_module.HackerNewsCrawler().fetch("daily", limit=30))
    assert default.snapshot_date == "2026-08-11"
