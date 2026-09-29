from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.app.core import scheduler
from backend.app.core.config import settings as app_settings
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
                "x_deleted_janitor",
                "dailyhot_hotlists",
                "github_project_daily_pipeline",
                "github_project_metrics_refresh",
                "github_fast_lane",
                "github_project_metrics_closing",
                "x_closing",
                "hackernews_closing",
                "news_closing",
                "daily_briefing",
                "subscription_dispatch",
                "conversation_cleanup",
                "ui_library_discovery",
                "ui_library_x_discovery",
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
                "x_deleted_janitor",
                "X 已删除推文定期清理",
                {"hour": "*/6", "minute": "11", "second": "0"},
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
                "GitHub 项目库当天指标每两小时刷新（含新越线项目富化补跑）",
                {"hour": "1-23/2", "minute": "17", "second": "0"},
                True,
                3600,
            ),
            (
                "github_fast_lane",
                "GitHub 新仓快车道（近 7 天新建越线项目每 15 分钟入库）",
                {"minute": "10,25,40,55", "second": "0"},
                True,
                600,
            ),
            # 关榜采集（PR4a/PR4b）：次日 00:3x 昨日归属，misfire 宽限 30 分钟
            (
                "github_project_metrics_closing",
                "GitHub 项目库指标关榜刷新（昨日切片）",
                {"hour": "0", "minute": "33", "second": "0"},
                False,
                1800,
            ),
            (
                "x_closing",
                "X 关注账号推文关榜采集（昨日归属）",
                {"hour": "0", "minute": "31", "second": "0"},
                False,
                1800,
            ),
            (
                "hackernews_closing",
                "Hacker News 关榜采集（昨日归属）",
                {"hour": "0", "minute": "35", "second": "0"},
                False,
                1800,
            ),
            (
                "news_closing",
                "Techmeme 科技新闻关榜采集（昨日归属）",
                {"hour": "0", "minute": "36", "second": "0"},
                False,
                1800,
            ),
        ]
        for (_, kwargs), (job_id, name, fields, coalesce, grace) in zip(
            fake_scheduler.add_job_calls[:16], expected_source_jobs, strict=True
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

        briefing = fake_scheduler.add_job_calls[16][1]
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

        dispatch = fake_scheduler.add_job_calls[17][1]
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

        cleanup = fake_scheduler.add_job_calls[18][1]
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
        x_deleted_janitor = AsyncMock()

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
                "_run_x_deleted_janitor_job",
                new=x_deleted_janitor,
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
            asyncio.run(callbacks["x_deleted_janitor"]())  # type: ignore[operator]
        daily_pipeline.assert_awaited_once()
        metrics_refresh.assert_awaited_once()
        single_source.assert_awaited_once()
        x_credentials_probe.assert_awaited_once()
        x_deleted_janitor.assert_awaited_once()

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
        x_deleted_janitor = AsyncMock()
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
                "_run_x_deleted_janitor_job",
                new=x_deleted_janitor,
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
            asyncio.run(runtime._run_x_deleted_janitor_job())
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
            enrichment=repositories.github_enrichment,
            documents=repositories.documents,
            github_lock=runtime._github_job_lock,
            logo_repository=metrics_refresh.await_args.kwargs["logo_repository"],
        )
        from backend.app.repositories.postgres_github_logo_repository import PostgresGitHubLogoRepository

        self.assertIsInstance(metrics_refresh.await_args.kwargs["logo_repository"], PostgresGitHubLogoRepository)
        x_credentials_probe.assert_awaited_once_with(
            repositories=repositories,
            x_lock=runtime._x_operation_lock,
        )
        x_deleted_janitor.assert_awaited_once_with(
            repositories=repositories,
            x_lock=runtime._x_operation_lock,
        )
        daily_briefing.assert_awaited_once_with(
            repositories,
            redis_client=None,
            on_source_failed=runtime._handle_briefing_source_failed,
        )
        subscription_dispatch.assert_awaited_once_with(repositories, redis_client=None)
        conversation_cleanup.assert_awaited_once_with(repositories.conversations)
        semantic_warmup.assert_awaited_once_with(semantic_warmup_callback)

    def test_runtime_forwards_redis_client_to_briefing_jobs(self) -> None:
        """构造注入的 redis_client 透传至简报/订阅派发任务，启用邮件池配额护栏。"""
        repositories = MagicMock()
        sentinel = object()
        runtime = scheduler.ApplicationSchedulerRuntime(
            repositories,
            redis_client=sentinel,
        )
        daily_briefing = AsyncMock()
        subscription_dispatch = AsyncMock()

        with (
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
        ):
            asyncio.run(runtime._run_daily_briefing_job())
            asyncio.run(runtime._run_subscription_dispatch_job())

        daily_briefing.assert_awaited_once_with(
            repositories,
            redis_client=sentinel,
            on_source_failed=runtime._handle_briefing_source_failed,
        )
        subscription_dispatch.assert_awaited_once_with(
            repositories, redis_client=sentinel
        )

    def test_module_jobs_forward_redis_client_to_dispatch_layer(self) -> None:
        """模块级 job 函数把 redis_client 继续透传到 services 派发层。"""
        repositories = MagicMock()
        repositories.tracking = None
        sentinel = object()

        with patch.object(
            scheduler, "run_daily_briefing_dispatch", new=AsyncMock()
        ) as dispatch_mock:
            asyncio.run(
                scheduler._run_daily_briefing_job(
                    repositories, redis_client=sentinel
                )
            )
        dispatch_mock.assert_awaited_once_with(
            repositories, redis_client=sentinel, on_source_failed=None
        )

        with patch(
            "backend.app.services.push.dispatch_service.SubscriptionDispatchService"
        ) as service_cls:
            service_cls.return_value.dispatch_all = AsyncMock(return_value={})
            result = asyncio.run(
                scheduler._run_subscription_dispatch_job(
                    repositories, redis_client=sentinel
                )
            )
        self.assertTrue(result)
        self.assertEqual(
            service_cls.call_args.kwargs.get("redis_client"),
            sentinel,
        )

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


class SchedulerXCredentialsProbeJobTests(unittest.TestCase):
    """x_credentials_probe 调度入口与池测活函数的委托契约。"""

    def test_job_delegates_enabled_pool_first_handle_and_update_callback(self) -> None:
        credentials = [
            {"id": 1, "auth_token": "test-auth-primary", "ct0": "test-ct0-primary"},
            {"id": 2, "auth_token": "test-auth-backup", "ct0": "test-ct0-backup"},
        ]
        repositories = MagicMock()
        repositories.x_credentials.list_enabled_x_credentials.return_value = credentials
        repositories.x_watch_accounts.list_enabled_x_handles.return_value = [
            "openai",
            "anthropic",
        ]
        probe_results = [
            {"credential_id": 1, "status": "failed", "message": "x_rate_limited"},
            {"credential_id": 2, "status": "succeeded", "message": "成功拉取 1 条近期推文"},
        ]
        probe_pool = MagicMock(return_value=probe_results)
        x_lock = asyncio.Lock()

        with patch.object(scheduler, "probe_all_x_credentials", new=probe_pool):
            succeeded = asyncio.run(
                scheduler._run_x_credentials_probe_job(
                    repositories=repositories,
                    x_lock=x_lock,
                )
            )

        self.assertTrue(succeeded)
        repositories.x_credentials.list_enabled_x_credentials.assert_called_once_with()
        repositories.x_watch_accounts.list_enabled_x_handles.assert_called_once_with()
        probe_pool.assert_called_once_with(
            credentials,
            "openai",
            update_result=repositories.x_credentials.update_x_credential_test_result,
        )
        # 只传入首个启用 handle；凭证池整体原样透传给池测活。
        self.assertEqual(probe_pool.call_args.args[0], credentials)
        self.assertEqual(probe_pool.call_args.args[1], "openai")

    def test_job_without_watch_handle_still_delegates_pool(self) -> None:
        credentials = [
            {"id": 1, "auth_token": "test-auth-primary", "ct0": "test-ct0-primary"},
        ]
        repositories = MagicMock()
        repositories.x_credentials.list_enabled_x_credentials.return_value = credentials
        repositories.x_watch_accounts.list_enabled_x_handles.return_value = []
        probe_results = [
            {
                "credential_id": 1,
                "status": "failed",
                "message": "x_probe_no_watch_handle",
            },
        ]
        probe_pool = MagicMock(return_value=probe_results)

        with patch.object(scheduler, "probe_all_x_credentials", new=probe_pool):
            succeeded = asyncio.run(
                scheduler._run_x_credentials_probe_job(repositories=repositories)
            )

        self.assertTrue(succeeded)
        probe_pool.assert_called_once_with(
            credentials,
            "",
            update_result=repositories.x_credentials.update_x_credential_test_result,
        )

    def test_job_logs_only_safe_markers_and_counts(self) -> None:
        credentials = [
            {"id": 1, "auth_token": "test-auth-primary", "ct0": "test-ct0-primary"},
            {"id": 2, "auth_token": "test-auth-backup", "ct0": "test-ct0-backup"},
        ]
        repositories = MagicMock()
        repositories.x_credentials.list_enabled_x_credentials.return_value = credentials
        repositories.x_watch_accounts.list_enabled_x_handles.return_value = ["openai"]
        probe_pool = MagicMock(
            return_value=[
                {"credential_id": 1, "status": "failed", "message": "x_rate_limited"},
                {"credential_id": 2, "status": "succeeded", "message": "成功拉取 1 条近期推文"},
            ]
        )

        with (
            patch.object(scheduler, "probe_all_x_credentials", new=probe_pool),
            self.assertLogs(scheduler.logger, level="INFO") as captured,
        ):
            asyncio.run(scheduler._run_x_credentials_probe_job(repositories=repositories))

        joined = "\n".join(captured.output)
        self.assertIn("启用凭证 2 个", joined)
        self.assertIn("watch handle 可用", joined)
        self.assertIn("1/2 成功", joined)
        self.assertIn("x_rate_limited", joined)
        self.assertNotIn("test-auth-primary", joined)
        self.assertNotIn("test-ct0-backup", joined)


class SchedulerXSourceGateTests(unittest.TestCase):
    """x_source_enabled=False 时 X 链路任务（采集/测活/收尾）整体不注册。"""

    def _start(self, *, x_source_enabled: bool) -> _RecordingScheduler:
        events: list[str] = []
        fake_scheduler = _RecordingScheduler(events)
        loop = _RecordingLoop(events)
        runtime = scheduler.ApplicationSchedulerRuntime(
            MagicMock(),
            scheduler=fake_scheduler,  # type: ignore[arg-type]
            x_source_enabled=x_source_enabled,
            timezone_name="Asia/Shanghai",
        )
        with patch.object(
            scheduler.asyncio,
            "get_running_loop",
            return_value=loop,
        ):
            runtime.start()
        return fake_scheduler

    def test_x_jobs_skipped_when_source_disabled(self) -> None:
        fake_scheduler = self._start(x_source_enabled=False)

        registered = [kwargs["id"] for _, kwargs in fake_scheduler.add_job_calls]
        self.assertNotIn("x_watchlist", registered)
        self.assertNotIn("x_credentials_probe", registered)
        self.assertNotIn("x_deleted_janitor", registered)
        self.assertNotIn("x_closing", registered)
        self.assertIn("arxiv_papers", registered)
        self.assertIn("daily_briefing", registered)
        self.assertIn("news_closing", registered)

    def test_x_jobs_registered_when_source_enabled(self) -> None:
        fake_scheduler = self._start(x_source_enabled=True)

        registered = [kwargs["id"] for _, kwargs in fake_scheduler.add_job_calls]
        self.assertIn("x_watchlist", registered)
        self.assertIn("x_credentials_probe", registered)
        self.assertIn("x_deleted_janitor", registered)
        self.assertIn("x_closing", registered)


class CreateSchedulerRuntimeXPluginGateTests(unittest.TestCase):
    """create_scheduler_runtime 的 X 门控：开关开但插件缺失时整体抑制。

    直接构造 ApplicationSchedulerRuntime 的旧行为不变（x_source_enabled
    默认 True）；策略收口在工厂——插件不可导入时按 fail closed 传
    x_source_enabled=False，X 链路任务不注册、在线配置亦无法启用。
    """

    _LOADER = "backend.app.services.source_plugins.load_x_transport_class"

    def _create(self) -> scheduler.ApplicationSchedulerRuntime:
        return scheduler.create_scheduler_runtime(MagicMock())

    def test_flag_on_plugin_missing_suppresses_x(self) -> None:
        with (
            patch.object(app_settings, "x_source_enabled", True),
            patch(self._LOADER, return_value=None),
            self.assertLogs("backend.app.core.scheduler", level="WARNING") as captured,
        ):
            runtime = self._create()

        self.assertIs(runtime._x_source_enabled, False)
        self.assertIn("X 源插件不可导入", "\n".join(captured.output))

    def test_flag_on_plugin_present_keeps_x(self) -> None:
        sentinel = type("XTransport", (), {})
        with (
            patch.object(app_settings, "x_source_enabled", True),
            patch(self._LOADER, return_value=sentinel),
        ):
            runtime = self._create()

        self.assertIs(runtime._x_source_enabled, True)

    def test_flag_off_never_touches_loader(self) -> None:
        with (
            patch.object(app_settings, "x_source_enabled", False),
            patch(self._LOADER) as loader_mock,
        ):
            runtime = self._create()

        self.assertIs(runtime._x_source_enabled, False)
        loader_mock.assert_not_called()
