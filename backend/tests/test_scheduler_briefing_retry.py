from __future__ import annotations

"""简报维度失败自动补跑：调度层编排契约。

覆盖：
  - 失败钩子即时排程一次性 date 触发补跑 job（距失败 5 分钟、按维度独立 id）
  - (目标日期, 维度) 额度计数：Redis 优先、进程内兜底、按日自然重置
  - 每日 3 次额度耗尽后落 ERROR（经 error_events 上监测页）且不再排程
  - 补跑链复用 dispatch 的 sources 子集与原目标日期
"""

import asyncio
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from backend.app.core import scheduler


class _RetryRecordingScheduler:
    """记录 add_job 调度的调度器替身（带 timezone，不真触发）。"""

    def __init__(self) -> None:
        self.timezone = ZoneInfo("Asia/Shanghai")
        self.add_job_calls: list[tuple[object, dict[str, object]]] = []

    def add_job(self, func: object, **kwargs: object) -> None:
        self.add_job_calls.append((func, kwargs))


def _runtime(
    *, redis_client: object | None = None
) -> tuple[scheduler.ApplicationSchedulerRuntime, _RetryRecordingScheduler]:
    fake = _RetryRecordingScheduler()
    runtime = scheduler.ApplicationSchedulerRuntime(
        MagicMock(),
        scheduler=fake,  # type: ignore[arg-type]
        redis_client=redis_client,
    )
    return runtime, fake


class BriefingRetrySchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_schedules_one_shot_retry_five_minutes_later(self) -> None:
        runtime, fake = _runtime()
        before = datetime.now(fake.timezone)

        await runtime._handle_briefing_source_failed(
            target_date="2026-09-03", source="github", error="stream broke"
        )

        self.assertEqual(len(fake.add_job_calls), 1)
        _, kwargs = fake.add_job_calls[0]
        self.assertEqual(kwargs["trigger"], "date")
        self.assertEqual(kwargs["id"], "daily_briefing_retry_github")
        self.assertIn("第 1/3 次", str(kwargs["name"]))
        self.assertTrue(kwargs["replace_existing"])
        self.assertEqual(kwargs["max_instances"], 1)
        self.assertEqual(kwargs["misfire_grace_time"], 3600)
        run_date = kwargs["run_date"]
        assert isinstance(run_date, datetime)
        delay = run_date - before
        self.assertGreaterEqual(delay, timedelta(minutes=4, seconds=55))
        self.assertLessEqual(delay, timedelta(minutes=5, seconds=5))

    async def test_scheduled_retry_callback_runs_retry_job(self) -> None:
        runtime, fake = _runtime()

        await runtime._handle_briefing_source_failed(
            target_date="2026-09-03", source="github", error="stream broke"
        )

        retry_func = fake.add_job_calls[0][0]
        self.assertTrue(asyncio.iscoroutinefunction(retry_func))
        with patch.object(
            scheduler, "_run_daily_briefing_retry_job", new=AsyncMock()
        ) as module_retry:
            await retry_func()

        module_retry.assert_awaited_once_with(
            runtime.repositories,
            target_date="2026-09-03",
            source="github",
            redis_client=None,
            on_source_failed=runtime._handle_briefing_source_failed,
        )

    async def test_chain_schedules_up_to_three_then_exhaustion_error(self) -> None:
        runtime, fake = _runtime()
        for attempt in range(1, 4):
            await runtime._handle_briefing_source_failed(
                target_date="2026-09-03", source="github", error=f"boom {attempt}"
            )
        self.assertEqual(len(fake.add_job_calls), 3)
        names = [str(kwargs["name"]) for _, kwargs in fake.add_job_calls]
        self.assertEqual(
            names,
            [
                "简报自动补跑（第 1/3 次）: github",
                "简报自动补跑（第 2/3 次）: github",
                "简报自动补跑（第 3/3 次）: github",
            ],
        )

        with self.assertLogs(scheduler.logger, "ERROR") as captured:
            await runtime._handle_briefing_source_failed(
                target_date="2026-09-03", source="github", error="boom 4"
            )

        # 第 4 次失败（第 3 次补跑仍败）不再排程，ERROR 落 error_events 上监测页。
        self.assertEqual(len(fake.add_job_calls), 3)
        message = "\n".join(captured.output)
        self.assertIn("已达每日上限", message)
        self.assertIn("2026-09-03", message)
        self.assertIn("github", message)
        self.assertIn("boom 4", message)

    async def test_exhaustion_is_per_source_and_per_date(self) -> None:
        runtime, fake = _runtime()
        for _ in range(4):
            await runtime._handle_briefing_source_failed(
                target_date="2026-09-03", source="github", error="boom"
            )
        github_jobs = len(fake.add_job_calls)
        self.assertEqual(github_jobs, 3)

        # 同日其他维度、次日同维度的额度各自独立。
        await runtime._handle_briefing_source_failed(
            target_date="2026-09-03", source="x", error="boom"
        )
        await runtime._handle_briefing_source_failed(
            target_date="2026-09-04", source="github", error="boom"
        )
        ids = [kwargs["id"] for _, kwargs in fake.add_job_calls]
        self.assertEqual(ids.count("daily_briefing_retry_x"), 1)
        self.assertEqual(ids.count("daily_briefing_retry_github"), 4)

    async def test_retry_counter_prefers_redis_and_sets_ttl(self) -> None:
        redis_client = MagicMock()
        redis_client.incr = AsyncMock(return_value=1)
        redis_client.expire = AsyncMock()
        runtime, fake = _runtime(redis_client=redis_client)

        await runtime._handle_briefing_source_failed(
            target_date="2026-09-03", source="github", error="boom"
        )

        redis_client.incr.assert_awaited_once_with(
            "aigc:briefing:retry:2026-09-03:github"
        )
        redis_client.expire.assert_awaited_once_with(
            "aigc:briefing:retry:2026-09-03:github", 172800
        )
        self.assertEqual(runtime._briefing_retry_counters, {})
        self.assertEqual(len(fake.add_job_calls), 1)

    async def test_redis_count_two_skips_expire_rewrite(self) -> None:
        redis_client = MagicMock()
        redis_client.incr = AsyncMock(return_value=2)
        redis_client.expire = AsyncMock()
        runtime, _ = _runtime(redis_client=redis_client)

        await runtime._handle_briefing_source_failed(
            target_date="2026-09-03", source="github", error="boom"
        )

        redis_client.expire.assert_not_awaited()

    async def test_redis_failure_falls_back_to_memory_counter(self) -> None:
        redis_client = MagicMock()
        redis_client.incr = AsyncMock(side_effect=ConnectionError("redis down"))
        runtime, fake = _runtime(redis_client=redis_client)

        with self.assertLogs(scheduler.logger, "WARNING"):
            await runtime._handle_briefing_source_failed(
                target_date="2026-09-03", source="github", error="boom"
            )

        self.assertEqual(
            runtime._briefing_retry_counters, {("2026-09-03", "github"): 1}
        )
        self.assertEqual(len(fake.add_job_calls), 1)

    async def test_memory_counter_prunes_stale_dates(self) -> None:
        runtime, _ = _runtime()
        runtime._briefing_retry_counters[("2026-09-01", "github")] = 3
        runtime._briefing_retry_counters[("2026-09-02", "x")] = 2

        await runtime._handle_briefing_source_failed(
            target_date="2026-09-03", source="github", error="boom"
        )

        self.assertEqual(
            runtime._briefing_retry_counters, {("2026-09-03", "github"): 1}
        )

    async def test_stopping_skips_scheduling_without_consuming_attempt(self) -> None:
        runtime, fake = _runtime()
        runtime._stopping = True

        await runtime._handle_briefing_source_failed(
            target_date="2026-09-03", source="github", error="boom"
        )

        self.assertEqual(fake.add_job_calls, [])
        self.assertEqual(runtime._briefing_retry_counters, {})

    async def test_retry_job_dispatches_subset_with_original_date(self) -> None:
        sentinel = object()
        runtime, _ = _runtime(redis_client=sentinel)

        with patch.object(
            scheduler, "_run_daily_briefing_retry_job", new=AsyncMock()
        ) as module_retry:
            await runtime._run_daily_briefing_retry_job("2026-09-03", "github")

        module_retry.assert_awaited_once_with(
            runtime.repositories,
            target_date="2026-09-03",
            source="github",
            redis_client=sentinel,
            on_source_failed=runtime._handle_briefing_source_failed,
        )


class BriefingRetryModuleJobTests(unittest.TestCase):
    def test_module_retry_job_forwards_subset_to_dispatch(self) -> None:
        repositories = MagicMock()
        sentinel = object()
        hook = AsyncMock()

        with patch.object(
            scheduler, "run_daily_briefing_dispatch", new=AsyncMock()
        ) as dispatch_mock:
            asyncio.run(
                scheduler._run_daily_briefing_retry_job(
                    repositories,
                    target_date="2026-09-03",
                    source="github",
                    redis_client=sentinel,
                    on_source_failed=hook,
                )
            )

        dispatch_mock.assert_awaited_once_with(
            repositories,
            redis_client=sentinel,
            sources=["github"],
            target_date="2026-09-03",
            on_source_failed=hook,
        )

    def test_main_job_forwards_failure_hook_to_dispatch(self) -> None:
        repositories = MagicMock()
        hook = AsyncMock()

        with patch.object(
            scheduler, "run_daily_briefing_dispatch", new=AsyncMock()
        ) as dispatch_mock:
            asyncio.run(
                scheduler._run_daily_briefing_job(
                    repositories, redis_client=None, on_source_failed=hook
                )
            )

        dispatch_mock.assert_awaited_once_with(
            repositories, redis_client=None, on_source_failed=hook
        )


if __name__ == "__main__":
    unittest.main()
