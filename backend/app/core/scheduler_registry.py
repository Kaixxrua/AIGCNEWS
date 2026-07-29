from __future__ import annotations

"""Typed, immutable scheduler job descriptors and pure projections."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol, TypedDict

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

CronValue = int | str
JobSource = Literal[
    "arxiv",
    "github",
    "news",
    "producthunt",
    "hackernews",
    "github_project_daily_pipeline",
    "github_project_metrics_refresh",
    "daily_briefing",
    "project_semantic_warmup",
    "conversation_cleanup",
]


@dataclass(frozen=True)
class CronSchedule:
    day: CronValue | None = None
    hour: CronValue | None = None
    minute: CronValue | None = None

    def as_kwargs(self) -> dict[str, CronValue]:
        return {
            name: value
            for name, value in (
                ("day", self.day),
                ("hour", self.hour),
                ("minute", self.minute),
            )
            if value is not None
        }


@dataclass(frozen=True)
class IntervalSchedule:
    seconds: int = 0
    minutes: int = 0


@dataclass(frozen=True)
class CronJobDescriptor:
    id: str
    source: JobSource
    name: str
    schedule: CronSchedule
    timezone: str = "Asia/Shanghai"
    replace_existing: bool = True
    max_instances: int = 1
    coalesce: bool | None = None
    misfire_grace_time: int = 3600


@dataclass(frozen=True)
class IntervalJobDescriptor:
    id: str
    source: JobSource
    name: str
    schedule: IntervalSchedule
    timezone: str
    replace_existing: bool = True
    max_instances: int = 1
    coalesce: bool | None = True
    misfire_grace_time: int = 300


JobDescriptor = CronJobDescriptor | IntervalJobDescriptor
SchedulerTrigger = CronTrigger | IntervalTrigger
SchedulerCallback = Callable[[], Awaitable[None]]
SingleSourceCallback = Callable[[str], Awaitable[None]]


SOURCE_JOB_DESCRIPTORS: tuple[CronJobDescriptor, ...] = (
    CronJobDescriptor(
        id="arxiv_papers",
        source="arxiv",
        name="HuggingFace Papers 论文采集",
        schedule=CronSchedule(minute=1),
        coalesce=False,
        misfire_grace_time=7200,
    ),
    CronJobDescriptor(
        id="github_trending",
        source="github",
        name="GitHub Trending 热榜采集",
        schedule=CronSchedule(minute=2),
        coalesce=False,
        misfire_grace_time=7200,
    ),
    CronJobDescriptor(
        id="news_techmeme",
        source="news",
        name="Techmeme 科技新闻采集",
        schedule=CronSchedule(minute=3),
        coalesce=False,
        misfire_grace_time=7200,
    ),
    CronJobDescriptor(
        id="producthunt",
        source="producthunt",
        name="Product Hunt 新品采集",
        schedule=CronSchedule(minute=4),
        coalesce=False,
        misfire_grace_time=7200,
    ),
    CronJobDescriptor(
        id="hackernews",
        source="hackernews",
        name="Hacker News AI 热帖采集",
        schedule=CronSchedule(minute=5),
        coalesce=False,
        misfire_grace_time=7200,
    ),
    CronJobDescriptor(
        id="github_project_daily_pipeline",
        source="github_project_daily_pipeline",
        name="GitHub 项目库每日流水线（入库、快照、热度打分、富化新增）",
        schedule=CronSchedule(hour=2, minute=0),
        coalesce=False,
        misfire_grace_time=7200,
    ),
    CronJobDescriptor(
        id="github_project_metrics_refresh",
        source="github_project_metrics_refresh",
        name="GitHub 项目库当天指标每两小时刷新",
        schedule=CronSchedule(hour="1-23/2", minute=17),
        coalesce=True,
        misfire_grace_time=3600,
    ),
)

DAILY_BRIEFING_JOB = CronJobDescriptor(
    id="daily_briefing",
    source="daily_briefing",
    name="每日自动简报生成（全维度）",
    schedule=CronSchedule(hour=8, minute=0),
)


def project_semantic_warmup_job_descriptor(
    *,
    timezone: str,
) -> IntervalJobDescriptor:
    return IntervalJobDescriptor(
        id="project_semantic_warmup",
        source="project_semantic_warmup",
        name="项目语义搜索链路预热",
        schedule=IntervalSchedule(minutes=30),
        timezone=timezone,
    )


CONVERSATION_CLEANUP_JOB = CronJobDescriptor(
    id="conversation_cleanup",
    source="conversation_cleanup",
    name="会话历史定期清理（7 天清 5 条）",
    schedule=CronSchedule(day="*/7", hour=3, minute=30),
)


def resolve_source_job_callback(
    source: JobSource,
    namespace: Mapping[str, Any],
) -> SchedulerCallback:
    """Resolve a source callback lazily from the scheduler module namespace."""
    callback_name = {
        "github_project_daily_pipeline": "_run_github_project_daily_pipeline_job",
        "github_project_metrics_refresh": "_run_github_project_metrics_refresh_job",
    }.get(source)
    if callback_name is not None:
        return namespace[callback_name]

    run_single_source: SingleSourceCallback = namespace["_run_single_source_job"]

    async def run_source_job(source_name: str = source) -> None:
        await run_single_source(source_name)

    return run_source_job


def build_trigger(descriptor: JobDescriptor) -> SchedulerTrigger:
    if isinstance(descriptor, CronJobDescriptor):
        return CronTrigger(
            **descriptor.schedule.as_kwargs(),
            timezone=descriptor.timezone,
        )
    return IntervalTrigger(
        seconds=descriptor.schedule.seconds,
        minutes=descriptor.schedule.minutes,
        timezone=descriptor.timezone,
    )


class ScheduledJob(Protocol):
    id: str
    name: str
    next_run_time: datetime | None
    trigger: object
    max_instances: int
    pending: bool


class SchedulerJobStatus(TypedDict):
    id: str
    name: str
    next_run_time: str | None
    trigger: str
    max_instances: int
    pending: bool


def project_job_status(job: ScheduledJob) -> SchedulerJobStatus:
    return {
        "id": job.id,
        "name": job.name,
        "next_run_time": (
            job.next_run_time.isoformat() if job.next_run_time else None
        ),
        "trigger": str(job.trigger),
        "max_instances": job.max_instances,
        "pending": job.pending,
    }


def project_scheduler_status(
    jobs: list[ScheduledJob] | tuple[ScheduledJob, ...],
) -> list[SchedulerJobStatus]:
    return [project_job_status(job) for job in jobs]
