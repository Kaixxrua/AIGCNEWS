from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.app.core import scheduler
from backend.app.core.scheduler_triggers import DailyWindowIntervalTrigger
from backend.app.repositories.scheduler_job_config_repository import SchedulerJobConfig


class _RecordingScheduler:
    def __init__(self, events: list[str], *, running: bool = False) -> None:
        self.events = events
        self.running = running
        self.add_job_calls: list[tuple[object, dict[str, object]]] = []
        self.jobs: list[object] = []

    def add_job(self, func: object, **kwargs: object) -> None:
        self.add_job_calls.append((func, kwargs))
        self.events.append(f"add_job:{kwargs['id']}")

    def start(self) -> None:
        self.events.append("start")
        self.running = True

    def pause(self) -> None:
        self.events.append("pause")

    def shutdown(self, *, wait: bool) -> None:
        self.events.append(f"shutdown:{wait}")
        self.running = False

    def get_jobs(self) -> list[object]:
        self.events.append("get_jobs")
        return self.jobs


class _RecordingLoop:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def create_task(self, coroutine: object) -> MagicMock:
        name = coroutine.cr_code.co_name  # type: ignore[attr-defined]
        self.events.append(f"create_task:{name}")
        coroutine.close()  # type: ignore[attr-defined]
        task = MagicMock()
        task.done.return_value = True
        return task


def _cron_fields(trigger: CronTrigger) -> dict[str, str]:
    return {field.name: str(field) for field in trigger.fields}


class SchedulerRegistrationContractTests(unittest.TestCase):
    def _start_scheduler(
        self,
        *,
        semantic_enabled: bool = False,
        poll_seconds: int = 7,
    ) -> tuple[_RecordingScheduler, list[str]]:
        del poll_seconds
        events: list[str] = []
        fake_scheduler = _RecordingScheduler(events)
        loop = _RecordingLoop(events)
        runtime = scheduler.ApplicationSchedulerRuntime(
            MagicMock(),
            scheduler=fake_scheduler,  # type: ignore[arg-type]
            semantic_search_enabled=semantic_enabled,
            timezone_name="Asia/Shanghai",
        )
        with patch.object(
            scheduler.asyncio,
            "get_running_loop",
            return_value=loop,
        ):
            runtime.start()
        return fake_scheduler, events

    def test_registers_base_jobs_in_order_with_frozen_triggers_and_options(self) -> None:
        fake_scheduler, _ = self._start_scheduler()

        self.assertEqual(
            [kwargs["id"] for _, kwargs in fake_scheduler.add_job_calls],
            [
                "arxiv_papers",
                "github_trending",
                "news_techmeme",
                "producthunt",
                "hackernews",
                "x_watchlist",
                "x_credentials_probe",
                "dailyhot_hotlists",
                "github_project_daily_pipeline",
                "github_project_metrics_refresh",
                "daily_briefing",
                "subscription_dispatch",
                "conversation_cleanup",
            ],
        )

        expected_source_jobs = [
            ("arxiv_papers", "HuggingFace Papers 论文采集", {"minute": "1", "second": "0"}, False, 7200),
            ("github_trending", "GitHub Trending 热榜采集", {"minute": "2", "second": "0"}, False, 7200),
            ("news_techmeme", "Techmeme 科技新闻采集", {"minute": "3", "second": "0"}, False, 7200),
            ("producthunt", "Product Hunt 新品采集", {"minute": "4", "second": "0"}, False, 7200),
            ("hackernews", "Hacker News AI 热帖采集", {"minute": "5", "second": "0"}, False, 7200),
            (
                "x_watchlist",
                "X 关注账号推文采集",
                {"hour": "*/2", "minute": "6", "second": "0"},
                True,
                3600,
            ),
            (
                "x_credentials_probe",
                "X 凭证池定时测活",
                {"hour": "*/2", "minute": "8", "second": "0"},
                True,
                3600,
            ),
            (
                "dailyhot_hotlists",
                "DailyHot 聚合热榜采集",
                {"minute": "7", "second": "0"},
                False,
                7200,
            ),
            (
                "github_project_daily_pipeline",
                "GitHub 项目库每日流水线（入库、快照、热度打分、富化新增）",
                {"hour": "2", "minute": "0", "second": "0"},
                False,
                7200,
            ),
            (
                "github_project_metrics_refresh",
                "GitHub 项目库当天指标每两小时刷新",
                {"hour": "1-23/2", "minute": "17", "second": "0"},
                True,
                3600,
            ),
        ]
        for (_, kwargs), (job_id, name, fields, coalesce, grace) in zip(
            fake_scheduler.add_job_calls[:10], expected_source_jobs, strict=True
        ):
            self.assertEqual(kwargs["id"], job_id)
            self.assertEqual(kwargs["name"], name)
            self.assertTrue(kwargs["replace_existing"])
            self.assertEqual(kwargs["max_instances"], 1)
            self.assertEqual(kwargs["coalesce"], coalesce)
            self.assertEqual(kwargs["misfire_grace_time"], grace)
            trigger = kwargs["trigger"]
            self.assertIsInstance(trigger, CronTrigger)
            actual_fields = {
                key: value
                for key, value in _cron_fields(trigger).items()
                if value != "*"
            }
            self.assertEqual(actual_fields, fields)
            self.assertEqual(str(trigger.timezone), "Asia/Shanghai")

        briefing = fake_scheduler.add_job_calls[10][1]
        self.assertEqual(
            {key: briefing[key] for key in ("id", "name", "replace_existing", "max_instances", "misfire_grace_time")},
            {
                "id": "daily_briefing",
                "name": "每日自动简报生成（全维度）",
                "replace_existing": True,
                "max_instances": 1,
                "misfire_grace_time": 3600,
            },
        )
        self.assertEqual(
            {key: value for key, value in _cron_fields(briefing["trigger"]).items() if value != "*"},
            {"hour": "8", "minute": "0", "second": "0"},
        )

        dispatch = fake_scheduler.add_job_calls[11][1]
        self.assertEqual(
            {key: dispatch[key] for key in ("id", "name", "replace_existing", "max_instances", "coalesce", "misfire_grace_time")},
            {
                "id": "subscription_dispatch",
                "name": "订阅简报派发（全频率幂等投递）",
                "replace_existing": True,
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 1800,
            },
        )
        self.assertEqual(
            {key: value for key, value in _cron_fields(dispatch["trigger"]).items() if value != "*"},
            {"minute": "*/30", "second": "0"},
        )

        cleanup = fake_scheduler.add_job_calls[12][1]
        self.assertEqual(
            {key: cleanup[key] for key in ("id", "name", "replace_existing", "max_instances", "misfire_grace_time")},
            {
                "id": "conversation_cleanup",
                "name": "会话历史定期清理（7 天清 5 条）",
                "replace_existing": True,
                "max_instances": 1,
                "misfire_grace_time": 3600,
            },
        )
        self.assertEqual(
            {key: value for key, value in _cron_fields(cleanup["trigger"]).items() if value != "*"},
            {"day": "*/7", "hour": "3", "minute": "30", "second": "0"},
        )

    def test_resolves_monkeypatched_callbacks_when_jobs_are_registered(self) -> None:
        single_source = AsyncMock()
        daily_pipeline = AsyncMock()
        metrics_refresh = AsyncMock()
        x_credentials_probe = AsyncMock()

        with (
            patch.object(scheduler, "_run_single_source_job", new=single_source),
            patch.object(
                scheduler,
                "_run_github_project_daily_pipeline_job",
                new=daily_pipeline,
            ),
            patch.object(
                scheduler,
                "_run_github_project_metrics_refresh_job",
                new=metrics_refresh,
            ),
            patch.object(
                scheduler,
                "_run_x_credentials_probe_job",
                new=x_credentials_probe,
            ),
        ):
            fake_scheduler, _ = self._start_scheduler()
            callbacks = {
                kwargs["id"]: callback
                for callback, kwargs in fake_scheduler.add_job_calls
            }
            asyncio.run(callbacks["github_project_daily_pipeline"]())  # type: ignore[operator]
            asyncio.run(callbacks["github_project_metrics_refresh"]())  # type: ignore[operator]
            asyncio.run(callbacks["arxiv_papers"]())  # type: ignore[operator]
            asyncio.run(callbacks["x_credentials_probe"]())  # type: ignore[operator]
        daily_pipeline.assert_awaited_once()
        metrics_refresh.assert_awaited_once()
        single_source.assert_awaited_once()
        x_credentials_probe.assert_awaited_once()

    def test_runtime_callbacks_forward_owned_repositories_and_lock(self) -> None:
        repositories = MagicMock()
        semantic_warmup_callback = MagicMock()
        runtime = scheduler.ApplicationSchedulerRuntime(
            repositories,
            semantic_search_warmup=semantic_warmup_callback,
        )
        single_source = AsyncMock()
        daily_pipeline = AsyncMock()
        metrics_refresh = AsyncMock()
        x_credentials_probe = AsyncMock()
        daily_briefing = AsyncMock()
        subscription_dispatch = AsyncMock()
        conversation_cleanup = AsyncMock()
        semantic_warmup = AsyncMock()

        with (
            patch.object(scheduler, "_run_single_source_job", new=single_source),
            patch.object(
                scheduler,
                "_run_github_project_daily_pipeline_job",
                new=daily_pipeline,
            ),
            patch.object(
                scheduler,
                "_run_github_project_metrics_refresh_job",
                new=metrics_refresh,
            ),
            patch.object(
                scheduler,
                "_run_x_credentials_probe_job",
                new=x_credentials_probe,
            ),
            patch.object(
                scheduler,
                "_run_daily_briefing_job",
                new=daily_briefing,
            ),
            patch.object(
                scheduler,
                "_run_subscription_dispatch_job",
                new=subscription_dispatch,
            ),
            patch.object(
                scheduler,
                "_run_conversation_cleanup_job",
                new=conversation_cleanup,
            ),
            patch.object(
                scheduler,
                "_run_project_semantic_warmup_job",
                new=semantic_warmup,
            ),
        ):
            asyncio.run(runtime._run_single_source_job("github"))
            asyncio.run(runtime._run_single_source_job("x"))
            asyncio.run(runtime._run_github_project_daily_pipeline_job())
            asyncio.run(runtime._run_github_project_metrics_refresh_job())
            asyncio.run(runtime._run_x_credentials_probe_job())
            asyncio.run(runtime._run_daily_briefing_job())
            asyncio.run(runtime._run_subscription_dispatch_job())
            asyncio.run(runtime._run_conversation_cleanup_job())
            asyncio.run(runtime._run_project_semantic_warmup_job())

        self.assertEqual(single_source.await_count, 2)
        single_source.assert_any_await(
            "github",
            repositories=repositories,
            github_lock=runtime._github_job_lock,
            x_lock=runtime._x_operation_lock,
            zero_ingest_reporter=runtime._zero_ingest_alerter.record,
        )
        single_source.assert_any_await(
            "x",
            repositories=repositories,
            github_lock=runtime._github_job_lock,
            x_lock=runtime._x_operation_lock,
            zero_ingest_reporter=runtime._zero_ingest_alerter.record,
        )
        daily_pipeline.assert_awaited_once_with(
            repositories=repositories,
            github_lock=runtime._github_job_lock,
        )
        metrics_refresh.assert_awaited_once_with(
            repository=repositories.github_ingestion,
            github_lock=runtime._github_job_lock,
        )
        x_credentials_probe.assert_awaited_once_with(
            repositories=repositories,
            x_lock=runtime._x_operation_lock,
        )
        daily_briefing.assert_awaited_once_with(repositories)
        subscription_dispatch.assert_awaited_once_with(repositories)
        conversation_cleanup.assert_awaited_once_with(repositories.conversations)
        semantic_warmup.assert_awaited_once_with(semantic_warmup_callback)

    def test_optional_jobs_freeze_intervals_options_and_startup_order(self) -> None:
        fake_scheduler, events = self._start_scheduler(
            semantic_enabled=True,
            poll_seconds=7,
        )
        calls = {kwargs["id"]: kwargs for _, kwargs in fake_scheduler.add_job_calls}

        semantic = calls["project_semantic_warmup"]
        self.assertIsInstance(semantic["trigger"], IntervalTrigger)
        self.assertEqual(semantic["trigger"].interval.total_seconds(), 1800)
        self.assertEqual(str(semantic["trigger"].timezone), "Asia/Shanghai")
        self.assertEqual(
            {key: semantic[key] for key in ("name", "replace_existing", "max_instances", "coalesce", "misfire_grace_time")},
            {
                "name": "项目语义搜索链路预热",
                "replace_existing": True,
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 300,
            },
        )

        self.assertNotIn("project_catalog_sync", calls)

        start_index = events.index("start")
        self.assertEqual(
            events[start_index : start_index + 4],
            [
                "start",
                "create_task:_reconcile_recent_arxiv_daily_snapshots",
                "create_task:_reconcile_current_github_project_metrics",
                "get_jobs",
            ],
        )

    def test_job_config_overrides_replace_triggers_and_skip_disabled_jobs(self) -> None:
        from datetime import time

        events: list[str] = []
        fake_scheduler = _RecordingScheduler(events)
        overrides = {
            "arxiv_papers": SchedulerJobConfig(
                job_id="arxiv_papers",
                start_time=time(9, 0),
                end_time=time(17, 0),
                interval_minutes=90,
                enabled=True,
            ),
            "daily_briefing": SchedulerJobConfig(
                job_id="daily_briefing",
                start_time=time(8, 0),
                end_time=time(8, 1),
                interval_minutes=1440,
                enabled=False,
            ),
        }
        runtime = scheduler.ApplicationSchedulerRuntime(
            MagicMock(),
            scheduler=fake_scheduler,  # type: ignore[arg-type]
            job_config_overrides=overrides,
        )
        with patch.object(scheduler.asyncio, "get_running_loop", return_value=_RecordingLoop(events)):
            runtime.start()

        calls = {kwargs["id"]: kwargs for _, kwargs in fake_scheduler.add_job_calls}
        self.assertIn("arxiv_papers", calls)
        self.assertIsInstance(calls["arxiv_papers"]["trigger"], DailyWindowIntervalTrigger)
        self.assertEqual(calls["arxiv_papers"]["trigger"].start_time, time(9, 0))
        self.assertEqual(calls["arxiv_papers"]["trigger"].end_time, time(17, 0))
        self.assertEqual(calls["arxiv_papers"]["trigger"].interval.total_seconds(), 5400)

        self.assertNotIn("daily_briefing", calls)

        # Jobs without overrides keep their default cron triggers.
        self.assertIsInstance(calls["github_trending"]["trigger"], CronTrigger)

    def test_running_scheduler_skips_registration_and_startup_work(self) -> None:
        events: list[str] = []
        fake_scheduler = _RecordingScheduler(events, running=True)
        runtime = scheduler.ApplicationSchedulerRuntime(
            MagicMock(),
            scheduler=fake_scheduler,  # type: ignore[arg-type]
        )
        with patch.object(scheduler.asyncio, "get_running_loop") as get_loop:
            runtime.start()

        self.assertEqual(events, [])
        self.assertEqual(fake_scheduler.add_job_calls, [])
        get_loop.assert_not_called()


class SchedulerLifecycleAndStatusContractTests(unittest.TestCase):
    def test_status_is_empty_when_stopped_and_projects_running_jobs_in_order(self) -> None:
        stopped = SimpleNamespace(running=False)
        runtime = scheduler.ApplicationSchedulerRuntime(
            MagicMock(),
            scheduler=stopped,  # type: ignore[arg-type]
        )
        self.assertEqual(runtime.status(), [])

        first_time = datetime(2026, 7, 27, 1, 2, tzinfo=timezone.utc)
        jobs = [
            SimpleNamespace(
                id="first",
                name="First",
                next_run_time=first_time,
                trigger="cron[first]",
                max_instances=1,
                pending=False,
            ),
            SimpleNamespace(
                id="second",
                name="Second",
                next_run_time=None,
                trigger="interval[second]",
                max_instances=2,
                pending=True,
            ),
        ]
        running = SimpleNamespace(running=True, get_jobs=MagicMock(return_value=jobs))
        runtime = scheduler.ApplicationSchedulerRuntime(
            MagicMock(),
            scheduler=running,  # type: ignore[arg-type]
        )
        status = runtime.status()

        self.assertEqual(
            status,
            [
                {
                    "id": "first",
                    "name": "First",
                    "next_run_time": first_time.isoformat(),
                    "trigger": "cron[first]",
                    "max_instances": 1,
                    "pending": False,
                },
                {
                    "id": "second",
                    "name": "Second",
                    "next_run_time": None,
                    "trigger": "interval[second]",
                    "max_instances": 2,
                    "pending": True,
                },
            ],
        )

    def test_stop_drains_owned_tasks_before_returning(self) -> None:
        async def run() -> None:
            events: list[str] = []
            stopped = _RecordingScheduler(events, running=False)
            runtime = scheduler.ApplicationSchedulerRuntime(
                MagicMock(),
                scheduler=stopped,  # type: ignore[arg-type]
            )
            release = asyncio.Event()

            async def operation() -> None:
                events.append("operation:start")
                await release.wait()
                events.append("operation:done")

            task = asyncio.create_task(operation())
            runtime._active_tasks.add(task)
            await asyncio.sleep(0)
            stop_task = asyncio.create_task(runtime.stop())
            await asyncio.sleep(0)

            self.assertFalse(stop_task.done())
            release.set()
            await stop_task
            self.assertEqual(events, ["operation:start", "operation:done"])
            self.assertEqual(runtime._active_tasks, set())

        asyncio.run(run())

    def test_stop_pauses_scheduler_before_shutdown_and_is_idempotent(self) -> None:
        events: list[str] = []
        running = _RecordingScheduler(events, running=True)
        runtime = scheduler.ApplicationSchedulerRuntime(
            MagicMock(),
            scheduler=running,  # type: ignore[arg-type]
        )

        asyncio.run(runtime.stop())
        asyncio.run(runtime.stop())

        self.assertEqual(events, ["pause", "shutdown:False"])

    def test_stop_extends_grace_once_and_drains_task_finishing_in_window(self) -> None:
        async def run(warning: MagicMock, error: MagicMock) -> None:
            runtime = scheduler.ApplicationSchedulerRuntime(
                MagicMock(),
                scheduler=_RecordingScheduler([], running=False),  # type: ignore[arg-type]
                shutdown_grace_seconds=30.0,
            )
            release = asyncio.Event()

            async def operation() -> None:
                await release.wait()

            task = asyncio.create_task(operation())
            runtime._active_tasks.add(task)

            real_wait = asyncio.wait
            wait_calls: list[float] = []

            async def fake_wait(
                fs: object, *, timeout: float
            ) -> tuple[set[object], set[object]]:
                wait_calls.append(timeout)
                if len(wait_calls) == 1:
                    # 首个宽限期到期时任务仍在运行。
                    return set(), set(fs)  # type: ignore[arg-type]
                release.set()
                return await real_wait(fs, timeout=timeout)  # type: ignore[arg-type]

            with patch.object(scheduler.asyncio, "wait", fake_wait):
                await runtime.stop()

            self.assertEqual(wait_calls, [30.0, 30.0])
            warning.assert_called_once()
            error.assert_not_called()
            self.assertFalse(task.cancelled())
            self.assertEqual(runtime._active_tasks, set())

        with (
            patch.object(scheduler.logger, "warning") as warning,
            patch.object(scheduler.logger, "error") as error,
        ):
            asyncio.run(run(warning, error))

    def test_stop_cancels_tasks_outliving_extended_grace_period(self) -> None:
        async def run(warning: MagicMock, error: MagicMock) -> None:
            runtime = scheduler.ApplicationSchedulerRuntime(
                MagicMock(),
                scheduler=_RecordingScheduler([], running=False),  # type: ignore[arg-type]
                shutdown_grace_seconds=0.0,
            )
            never = asyncio.Event()

            async def operation() -> None:
                await never.wait()

            task = asyncio.create_task(operation())
            runtime._active_tasks.add(task)

            async def fake_wait(
                fs: object, *, timeout: float
            ) -> tuple[set[object], set[object]]:
                # 两个宽限窗口到期时任务都未结束。
                return set(), set(fs)  # type: ignore[arg-type]

            with patch.object(scheduler.asyncio, "wait", fake_wait):
                await asyncio.wait_for(runtime.stop(), timeout=5.0)

            warning.assert_called_once()
            error.assert_called_once()
            self.assertTrue(task.cancelled())
            self.assertEqual(runtime._active_tasks, set())

        with (
            patch.object(scheduler.logger, "warning") as warning,
            patch.object(scheduler.logger, "error") as error,
        ):
            asyncio.run(run(warning, error))

    def test_tracked_job_survives_scheduler_wrapper_cancellation(self) -> None:
        async def run() -> None:
            runtime = scheduler.ApplicationSchedulerRuntime(MagicMock())
            release = asyncio.Event()
            completed = asyncio.Event()

            async def operation() -> None:
                await release.wait()
                completed.set()

            wrapper = asyncio.create_task(runtime._run_tracked(operation))
            await asyncio.sleep(0)
            wrapper.cancel()
            await asyncio.sleep(0)

            self.assertFalse(wrapper.done())
            release.set()
            await wrapper
            self.assertTrue(completed.is_set())
            self.assertEqual(runtime._active_tasks, set())

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
