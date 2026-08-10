"""调度器连续零入库去抖告警测试。

背景：采集 job 零入库时正常返回 True（不抛异常），_ConsecutiveFailureAlerter
不计数——代理断供两天零入库却零告警的事故即源于此。_ZeroIngestAlerter 按源
统计连续零入库轮次，到达阈值经 notify_ops_alert 链路告警一次，入库 > 0 重置。

覆盖：
  - _ZeroIngestAlerter：到达阈值告警一次、不重复、成功后重置并重臂、
    非盯防源忽略、notifier 异常不炸采集；
  - 环境变量解析：阈值与盯防源集合的覆盖与兜底；
  - ApplicationSchedulerRuntime._run_single_source_job：把模块级 job 上报的
    （源, 入库数）喂给零入库告警器。
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from backend.app.core import scheduler
from backend.app.core.scheduler import (
    ApplicationSchedulerRuntime,
    _ZeroIngestAlerter,
)


class ZeroIngestAlerterTests(unittest.TestCase):
    def test_alerts_exactly_once_at_threshold(self) -> None:
        calls: list[tuple[str, int, str]] = []
        alerter = _ZeroIngestAlerter(
            threshold=3,
            notifier=lambda job_id, count, detail: calls.append((job_id, count, detail)),
        )

        alerter.record("arxiv", 0)
        alerter.record("arxiv", 0)
        assert calls == []

        alerter.record("arxiv", 0)
        assert len(calls) == 1
        assert calls[0][0] == "zero-ingest:arxiv"
        assert calls[0][1] == 3

        # 第 4、5 轮连续零入库不再重复发信
        alerter.record("arxiv", 0)
        alerter.record("arxiv", 0)
        assert len(calls) == 1

    def test_nonzero_resets_and_rearms(self) -> None:
        calls: list[tuple[str, int, str]] = []
        alerter = _ZeroIngestAlerter(
            threshold=2,
            notifier=lambda job_id, count, detail: calls.append((job_id, count, detail)),
        )

        alerter.record("github", 0)
        alerter.record("github", 30)  # 有入库 → 计数清零
        alerter.record("github", 0)
        assert calls == []

        alerter.record("github", 0)
        assert len(calls) == 1
        assert calls[0][0] == "zero-ingest:github"

    def test_unwatched_sources_ignored(self) -> None:
        calls: list[str] = []
        alerter = _ZeroIngestAlerter(
            threshold=1,
            notifier=lambda job_id, count, detail: calls.append(job_id),
        )

        # x 当日过滤后零入库是常态、dailyhot 上游可选未部署：默认均不盯防
        alerter.record("x", 0)
        alerter.record("dailyhot", 0)
        assert calls == []

        alerter.record("arxiv", 0)
        assert calls == ["zero-ingest:arxiv"]

    def test_sources_tracked_independently(self) -> None:
        calls: list[str] = []
        alerter = _ZeroIngestAlerter(
            threshold=2,
            notifier=lambda job_id, count, detail: calls.append(job_id),
        )
        alerter.record("arxiv", 0)
        alerter.record("news", 0)
        alerter.record("news", 0)
        assert calls == ["zero-ingest:news"]

    def test_notifier_exception_is_swallowed(self) -> None:
        def broken(job_id: str, count: int, detail: str) -> None:
            raise RuntimeError("smtp down")

        alerter = _ZeroIngestAlerter(threshold=1, notifier=broken)
        alerter.record("arxiv", 0)  # 不抛出


class ZeroIngestEnvTests(unittest.TestCase):
    def test_threshold_env_override_and_fallback(self) -> None:
        with patch.dict(os.environ, {"SCHEDULER_ZERO_INGEST_ALERT_THRESHOLD": "5"}):
            assert scheduler._zero_ingest_threshold_from_env() == 5
        with patch.dict(os.environ, {"SCHEDULER_ZERO_INGEST_ALERT_THRESHOLD": "junk"}):
            assert scheduler._zero_ingest_threshold_from_env() == 3
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCHEDULER_ZERO_INGEST_ALERT_THRESHOLD", None)
            assert scheduler._zero_ingest_threshold_from_env() == 3

    def test_watch_sources_env_override_and_fallback(self) -> None:
        with patch.dict(
            os.environ, {"SCHEDULER_ZERO_INGEST_WATCH_SOURCES": "arxiv, github ,,"}
        ):
            assert scheduler._zero_ingest_watch_sources_from_env() == ("arxiv", "github")
        with patch.dict(os.environ, {"SCHEDULER_ZERO_INGEST_WATCH_SOURCES": " , "}):
            assert scheduler._zero_ingest_watch_sources_from_env() == (
                "arxiv",
                "github",
                "news",
                "producthunt",
                "hackernews",
            )
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCHEDULER_ZERO_INGEST_WATCH_SOURCES", None)
            assert scheduler._zero_ingest_watch_sources_from_env() == (
                "arxiv",
                "github",
                "news",
                "producthunt",
                "hackernews",
            )


class RuntimeZeroIngestWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_reported_zeros_feed_alerter(self) -> None:
        calls: list[tuple[str, int, str]] = []
        runtime = ApplicationSchedulerRuntime(
            MagicMock(),
            scheduler=MagicMock(running=False),
            zero_ingest_threshold=3,
            zero_ingest_notifier=lambda job_id, count, detail: calls.append(
                (job_id, count, detail)
            ),
        )

        async def fake_job(source_name: str, **kwargs: object) -> bool:
            reporter = kwargs.get("zero_ingest_reporter")
            assert callable(reporter)
            reporter(source_name, 0)
            return True

        with patch.object(scheduler, "_run_single_source_job", new=fake_job):
            for _ in range(3):
                await runtime._run_single_source_job("arxiv")

        assert len(calls) == 1
        assert calls[0][0] == "zero-ingest:arxiv"
        assert calls[0][1] == 3

    async def test_nonzero_round_prevents_alert(self) -> None:
        calls: list[tuple[str, int, str]] = []
        runtime = ApplicationSchedulerRuntime(
            MagicMock(),
            scheduler=MagicMock(running=False),
            zero_ingest_threshold=2,
            zero_ingest_notifier=lambda job_id, count, detail: calls.append(
                (job_id, count, detail)
            ),
        )

        ingested_sequence = iter([0, 12, 0])

        async def fake_job(source_name: str, **kwargs: object) -> bool:
            reporter = kwargs.get("zero_ingest_reporter")
            assert callable(reporter)
            reporter(source_name, next(ingested_sequence))
            return True

        with patch.object(scheduler, "_run_single_source_job", new=fake_job):
            for _ in range(3):
                await runtime._run_single_source_job("news")

        assert calls == []


if __name__ == "__main__":
    unittest.main()
