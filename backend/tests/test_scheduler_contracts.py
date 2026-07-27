from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.app.core import scheduler


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

    def shutdown(self, *, wait: bool) -> None:
        self.events.append(f"shutdown:{wait}")
        self.running = False

    def get_jobs(self) -> list[object]:
        self.events.append("get_jobs")
        return self.jobs


class _RecordingLoop:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def create_task(self, coroutine: object) -> None:
        name = coroutine.cr_code.co_name  # type: ignore[attr-defined]
        self.events.append(f"create_task:{name}")
        coroutine.close()  # type: ignore[attr-defined]


def _cron_fields(trigger: CronTrigger) -> dict[str, str]:
    return {field.name: str(field) for field in trigger.fields}


class SchedulerRegistrationContractTests(unittest.TestCase):
    def _start_scheduler(
        self,
        *,
        semantic_enabled: bool = False,
        catalog_sync_enabled: bool = False,
        poll_seconds: int = 7,
    ) -> tuple[_RecordingScheduler, list[str]]:
        events: list[str] = []
        fake_scheduler = _RecordingScheduler(events)
        loop = _RecordingLoop(events)
        with (
            patch.object(scheduler, "get_scheduler", return_value=fake_scheduler),
            patch.object(scheduler.asyncio, "get_running_loop", return_value=loop),
            patch(
                "backend.app.core.config.settings.project_semantic_search_enabled",
                semantic_enabled,
            ),
            patch(
                "backend.app.core.config.settings.project_catalog_sync_worker_enabled",
                catalog_sync_enabled,
            ),
            patch(
                "backend.app.core.config.settings.project_catalog_sync_poll_seconds",
                poll_seconds,
            ),
            patch(
                "backend.app.core.config.settings.scheduler_timezone",
                "Asia/Shanghai",
            ),
        ):
            scheduler.start_scheduler()
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
                "github_project_daily_pipeline",
                "github_project_metrics_refresh",
                "daily_briefing",
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
            fake_scheduler.add_job_calls[:7], expected_source_jobs, strict=True
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

        briefing = fake_scheduler.add_job_calls[7][1]
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

        cleanup = fake_scheduler.add_job_calls[8][1]
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
        ):
            fake_scheduler, _ = self._start_scheduler()

        callbacks = {
            kwargs["id"]: callback
            for callback, kwargs in fake_scheduler.add_job_calls
        }
        self.assertIs(callbacks["github_project_daily_pipeline"], daily_pipeline)
        self.assertIs(callbacks["github_project_metrics_refresh"], metrics_refresh)

        asyncio.run(callbacks["arxiv_papers"]())  # type: ignore[operator]
        single_source.assert_awaited_once_with("arxiv")

    def test_optional_jobs_freeze_intervals_options_and_startup_order(self) -> None:
        fake_scheduler, events = self._start_scheduler(
            semantic_enabled=True,
            catalog_sync_enabled=True,
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

        catalog = calls["project_catalog_sync"]
        self.assertIsInstance(catalog["trigger"], IntervalTrigger)
        self.assertEqual(catalog["trigger"].interval.total_seconds(), 7)
        self.assertEqual(str(catalog["trigger"].timezone), "Asia/Shanghai")
        self.assertEqual(
            {key: catalog[key] for key in ("name", "replace_existing", "max_instances", "coalesce", "misfire_grace_time")},
            {
                "name": "MySQL 到 PostgreSQL 项目目录同步",
                "replace_existing": True,
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 30,
            },
        )

        start_index = events.index("start")
        self.assertEqual(
            events[start_index : start_index + 5],
            [
                "start",
                "create_task:_reconcile_recent_arxiv_daily_snapshots",
                "create_task:_reconcile_current_github_project_metrics",
                "create_task:_run_project_catalog_sync_job",
                "get_jobs",
            ],
        )

    def test_running_scheduler_skips_registration_and_startup_work(self) -> None:
        events: list[str] = []
        fake_scheduler = _RecordingScheduler(events, running=True)
        with (
            patch.object(scheduler, "get_scheduler", return_value=fake_scheduler),
            patch.object(scheduler.asyncio, "get_running_loop") as get_loop,
        ):
            scheduler.start_scheduler()

        self.assertEqual(events, [])
        self.assertEqual(fake_scheduler.add_job_calls, [])
        get_loop.assert_not_called()


class SchedulerLifecycleAndStatusContractTests(unittest.TestCase):
    def test_status_is_empty_when_stopped_and_projects_running_jobs_in_order(self) -> None:
        stopped = SimpleNamespace(running=False)
        with patch.object(scheduler, "get_scheduler", return_value=stopped):
            self.assertEqual(scheduler.get_scheduler_status(), [])

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
        with patch.object(scheduler, "get_scheduler", return_value=running):
            status = scheduler.get_scheduler_status()

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

    def test_stop_only_shuts_down_running_scheduler_without_waiting(self) -> None:
        events: list[str] = []
        running = _RecordingScheduler(events, running=True)
        with patch.object(scheduler, "get_scheduler", return_value=running):
            scheduler.stop_scheduler()
        self.assertEqual(events, ["shutdown:False"])

        stopped = _RecordingScheduler(events, running=False)
        with patch.object(scheduler, "get_scheduler", return_value=stopped):
            scheduler.stop_scheduler()
        self.assertEqual(events, ["shutdown:False"])

    def test_lifespan_starts_before_yield_and_stops_after_exit(self) -> None:
        events: list[str] = []

        @asynccontextmanager
        async def exercise_lifespan():
            async with scheduler.lifespan_scheduler(object()):
                events.append("inside")
                yield

        async def run() -> None:
            async with exercise_lifespan():
                self.assertEqual(events, ["start", "inside"])

        with (
            patch.object(scheduler, "start_scheduler", side_effect=lambda: events.append("start")) as start,
            patch.object(scheduler, "stop_scheduler", side_effect=lambda: events.append("stop")) as stop,
        ):
            import asyncio

            asyncio.run(run())

        self.assertEqual(events, ["start", "inside", "stop"])
        self.assertEqual(start.call_args_list, [call()])
        self.assertEqual(stop.call_args_list, [call()])


if __name__ == "__main__":
    unittest.main()
