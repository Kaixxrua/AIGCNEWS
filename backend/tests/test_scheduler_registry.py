from __future__ import annotations

import asyncio
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, time, timezone
from types import SimpleNamespace

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.app.core.scheduler_registry import (
    CONVERSATION_CLEANUP_JOB,
    DAILY_BRIEFING_JOB,
    SOURCE_JOB_DESCRIPTORS,
    CronJobDescriptor,
    CronSchedule,
    IntervalJobDescriptor,
    IntervalSchedule,
    WindowedIntervalJobDescriptor,
    apply_job_config,
    build_trigger,
    project_scheduler_status,
    project_semantic_warmup_job_descriptor,
    resolve_source_job_callback,
)
from backend.app.core.scheduler_triggers import DailyWindowIntervalTrigger
from backend.app.repositories.scheduler_job_config_repository import SchedulerJobConfig


def _cron_fields(trigger: CronTrigger) -> dict[str, str]:
    return {
        field.name: str(field)
        for field in trigger.fields
        if str(field) != "*"
    }


class SchedulerDescriptorTests(unittest.TestCase):
    def test_source_descriptors_freeze_current_order_triggers_and_options(self) -> None:
        expected = [
            ("arxiv_papers", "arxiv", "HuggingFace Papers 论文采集", {"minute": "1", "second": "0"}, False, 7200),
            ("github_trending", "github", "GitHub Trending 热榜采集", {"minute": "2", "second": "0"}, False, 7200),
            ("news_techmeme", "news", "Techmeme 科技新闻采集", {"minute": "3", "second": "0"}, False, 7200),
            ("producthunt", "producthunt", "Product Hunt 新品采集", {"minute": "4", "second": "0"}, False, 7200),
            ("hackernews", "hackernews", "Hacker News AI 热帖采集", {"minute": "5", "second": "0"}, False, 7200),
            (
                "x_watchlist",
                "x",
                "X 关注账号推文采集",
                {"hour": "*/2", "minute": "6", "second": "0"},
                True,
                3600,
            ),
            (
                "x_credentials_probe",
                "x_credentials_probe",
                "X 凭证池定时测活",
                {"hour": "*/2", "minute": "8", "second": "0"},
                True,
                3600,
            ),
            (
                "github_project_daily_pipeline",
                "github_project_daily_pipeline",
                "GitHub 项目库每日流水线（入库、快照、热度打分、富化新增）",
                {"hour": "2", "minute": "0", "second": "0"},
                False,
                7200,
            ),
            (
                "github_project_metrics_refresh",
                "github_project_metrics_refresh",
                "GitHub 项目库当天指标每两小时刷新",
                {"hour": "1-23/2", "minute": "17", "second": "0"},
                True,
                3600,
            ),
        ]

        self.assertIsInstance(SOURCE_JOB_DESCRIPTORS, tuple)
        for descriptor, (job_id, source, name, fields, coalesce, grace) in zip(
            SOURCE_JOB_DESCRIPTORS,
            expected,
            strict=True,
        ):
            self.assertIsInstance(descriptor, CronJobDescriptor)
            self.assertEqual(descriptor.id, job_id)
            self.assertEqual(descriptor.source, source)
            self.assertEqual(descriptor.name, name)
            self.assertTrue(descriptor.replace_existing)
            self.assertEqual(descriptor.max_instances, 1)
            self.assertEqual(descriptor.coalesce, coalesce)
            self.assertEqual(descriptor.misfire_grace_time, grace)

            trigger = build_trigger(descriptor)
            self.assertIsInstance(trigger, CronTrigger)
            self.assertEqual(_cron_fields(trigger), fields)
            self.assertEqual(str(trigger.timezone), "Asia/Shanghai")

        with self.assertRaises(FrozenInstanceError):
            SOURCE_JOB_DESCRIPTORS[0].name = "changed"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            SOURCE_JOB_DESCRIPTORS[0].schedule.minute = 9  # type: ignore[misc]

    def test_standalone_cron_descriptors_preserve_implicit_coalesce(self) -> None:
        cases = [
            (
                DAILY_BRIEFING_JOB,
                "daily_briefing",
                "每日自动简报生成（全维度）",
                {"hour": "8", "minute": "0", "second": "0"},
            ),
            (
                CONVERSATION_CLEANUP_JOB,
                "conversation_cleanup",
                "会话历史定期清理（7 天清 5 条）",
                {"day": "*/7", "hour": "3", "minute": "30", "second": "0"},
            ),
        ]
        for descriptor, job_id, name, fields in cases:
            self.assertEqual(descriptor.id, job_id)
            self.assertEqual(descriptor.name, name)
            self.assertIsNone(descriptor.coalesce)
            self.assertEqual(descriptor.misfire_grace_time, 3600)
            trigger = build_trigger(descriptor)
            self.assertIsInstance(trigger, CronTrigger)
            self.assertEqual(_cron_fields(trigger), fields)
            self.assertEqual(str(trigger.timezone), "Asia/Shanghai")

    def test_semantic_interval_factory_preserves_timezone(self) -> None:
        semantic = project_semantic_warmup_job_descriptor(timezone="UTC")
        semantic_trigger = build_trigger(semantic)
        self.assertIsInstance(semantic, IntervalJobDescriptor)
        self.assertIsInstance(semantic_trigger, IntervalTrigger)
        self.assertEqual(semantic_trigger.interval.total_seconds(), 1800)
        self.assertEqual(str(semantic_trigger.timezone), "UTC")
        self.assertTrue(semantic.coalesce)
        self.assertEqual(semantic.misfire_grace_time, 300)

    def test_build_trigger_returns_fresh_instances_without_mutating_descriptor(self) -> None:
        descriptor = CronJobDescriptor(
            id="test",
            source="arxiv",
            name="Test",
            schedule=CronSchedule(minute=1),
        )

        first = build_trigger(descriptor)
        second = build_trigger(descriptor)

        self.assertIsNot(first, second)
        self.assertEqual(descriptor.schedule, CronSchedule(minute=1))


class SchedulerCallbackResolutionTests(unittest.TestCase):
    def test_resolves_special_callback_from_namespace_at_registration_time(self) -> None:
        async def first() -> None:
            return None

        async def replacement() -> None:
            return None

        namespace = {"_run_github_project_daily_pipeline_job": first}
        self.assertIs(
            resolve_source_job_callback(
                "github_project_daily_pipeline",
                namespace,
            ),
            first,
        )

        namespace["_run_github_project_daily_pipeline_job"] = replacement
        self.assertIs(
            resolve_source_job_callback(
                "github_project_daily_pipeline",
                namespace,
            ),
            replacement,
        )

    def test_resolves_x_credentials_probe_callback_from_namespace(self) -> None:
        async def probe() -> None:
            return None

        namespace = {"_run_x_credentials_probe_job": probe}
        self.assertIs(
            resolve_source_job_callback("x_credentials_probe", namespace),
            probe,
        )

    def test_source_callback_preserves_source_default_and_registration_binding(self) -> None:
        calls: list[tuple[str, str]] = []

        async def first(source: str) -> None:
            calls.append(("first", source))

        async def replacement(source: str) -> None:
            calls.append(("replacement", source))

        namespace = {"_run_single_source_job": first}
        callback = resolve_source_job_callback("arxiv", namespace)
        namespace["_run_single_source_job"] = replacement

        asyncio.run(callback())
        asyncio.run(callback("github"))
        asyncio.run(resolve_source_job_callback("news", namespace)())

        self.assertEqual(
            calls,
            [
                ("first", "arxiv"),
                ("first", "github"),
                ("replacement", "news"),
            ],
        )


class SchedulerStatusProjectionTests(unittest.TestCase):
    def test_projects_jobs_in_order_with_iso_time_none_and_passthrough_values(self) -> None:
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

        self.assertEqual(
            project_scheduler_status(jobs),  # type: ignore[arg-type]
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
        self.assertEqual(project_scheduler_status([]), [])


class JobConfigOverrideTests(unittest.TestCase):
    def test_disabled_config_returns_none(self) -> None:
        descriptor = CronJobDescriptor(
            id="test",
            source="arxiv",
            name="Test",
            schedule=CronSchedule(minute=1),
        )
        config = SchedulerJobConfig(
            job_id="test",
            start_time=time(8, 0),
            end_time=time(20, 0),
            interval_minutes=60,
            enabled=False,
        )
        self.assertIsNone(apply_job_config(descriptor, config))

    def test_cron_descriptor_becomes_windowed(self) -> None:
        descriptor = CronJobDescriptor(
            id="arxiv_papers",
            source="arxiv",
            name="Papers",
            schedule=CronSchedule(minute=1),
            coalesce=False,
            misfire_grace_time=7200,
        )
        config = SchedulerJobConfig(
            job_id="arxiv_papers",
            start_time=time(9, 0),
            end_time=time(17, 0),
            interval_minutes=90,
        )
        overridden = apply_job_config(descriptor, config)
        self.assertIsInstance(overridden, WindowedIntervalJobDescriptor)
        assert isinstance(overridden, WindowedIntervalJobDescriptor)
        self.assertEqual(overridden.start_time, time(9, 0))
        self.assertEqual(overridden.end_time, time(17, 0))
        self.assertEqual(overridden.interval_minutes, 90)
        self.assertEqual(overridden.coalesce, False)
        self.assertEqual(overridden.misfire_grace_time, 7200)
        trigger = build_trigger(overridden)
        self.assertIsInstance(trigger, DailyWindowIntervalTrigger)

    def test_interval_descriptor_becomes_windowed(self) -> None:
        descriptor = IntervalJobDescriptor(
            id="warmup",
            source="project_semantic_warmup",
            name="Warmup",
            schedule=IntervalSchedule(minutes=30),
            timezone="Asia/Shanghai",
            coalesce=True,
            misfire_grace_time=300,
        )
        config = SchedulerJobConfig(
            job_id="warmup",
            start_time=time(0, 0),
            end_time=time(23, 59),
            interval_minutes=15,
        )
        overridden = apply_job_config(descriptor, config)
        self.assertIsInstance(overridden, WindowedIntervalJobDescriptor)
        assert isinstance(overridden, WindowedIntervalJobDescriptor)
        self.assertEqual(overridden.interval_minutes, 15)
        self.assertEqual(overridden.timezone, "Asia/Shanghai")
        self.assertEqual(overridden.coalesce, True)
        self.assertEqual(overridden.misfire_grace_time, 300)

    def test_windowed_descriptor_updates_schedule_fields(self) -> None:
        descriptor = WindowedIntervalJobDescriptor(
            id="warmup",
            source="project_semantic_warmup",
            name="Warmup",
            start_time=time(0, 0),
            end_time=time(23, 59),
            interval_minutes=30,
        )
        config = SchedulerJobConfig(
            job_id="warmup",
            start_time=time(10, 0),
            end_time=time(11, 0),
            interval_minutes=5,
        )
        overridden = apply_job_config(descriptor, config)
        self.assertIsInstance(overridden, WindowedIntervalJobDescriptor)
        assert isinstance(overridden, WindowedIntervalJobDescriptor)
        self.assertEqual(overridden.start_time, time(10, 0))
        self.assertEqual(overridden.end_time, time(11, 0))
        self.assertEqual(overridden.interval_minutes, 5)


if __name__ == "__main__":
    unittest.main()
