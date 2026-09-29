from __future__ import annotations

"""Typed, immutable scheduler job descriptors and pure projections."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Literal, Protocol, TypedDict

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.app.core.scheduler_triggers import DailyWindowIntervalTrigger

CronValue = int | str
JobSource = Literal[
    "arxiv",
    "github",
    "news",
    "producthunt",
    "hackernews",
    "x",
    "x_credentials_probe",
    "x_deleted_janitor",
    "dailyhot",
    "github_project_daily_pipeline",
    "github_project_metrics_refresh",
    "github_project_metrics_closing",
    "github_fast_lane",
    "x_closing",
    "hackernews_closing",
    "news_closing",
    "daily_briefing",
    "subscription_dispatch",
    "project_semantic_warmup",
    "conversation_cleanup",
    "x_media_warmup",
    "payment_order_closing",
    "ui_library_discovery",
    "ui_library_x_discovery",
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


@dataclass(frozen=True)
class WindowedIntervalJobDescriptor:
    id: str
    source: JobSource
    name: str
    start_time: time
    end_time: time
    interval_minutes: int
    timezone: str = "Asia/Shanghai"
    replace_existing: bool = True
    max_instances: int = 1
    coalesce: bool | None = True
    misfire_grace_time: int = 3600


JobDescriptor = CronJobDescriptor | IntervalJobDescriptor | WindowedIntervalJobDescriptor
SchedulerTrigger = CronTrigger | IntervalTrigger | DailyWindowIntervalTrigger
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
    # X 采集降频为每 2 小时一轮（其余源 hourly）：主账号 cookie 凭据，
    # 温和节奏优先；错过点火合并一次即可（coalesce=True）
    CronJobDescriptor(
        id="x_watchlist",
        source="x",
        name="X 关注账号推文采集",
        schedule=CronSchedule(hour="*/2", minute=6),
        coalesce=True,
        misfire_grace_time=3600,
    ),
    # X 凭证池测活：与采集错开 2 分钟，串行执行，避免与采集并发请求 X
    CronJobDescriptor(
        id="x_credentials_probe",
        source="x_credentials_probe",
        name="X 凭证池定时测活",
        schedule=CronSchedule(hour="*/2", minute=8),
        coalesce=True,
        misfire_grace_time=3600,
    ),
    # X 已删推文 janitor：6 小时一轮探测存量文档，错开采集（:06）与测活（:08）
    CronJobDescriptor(
        id="x_deleted_janitor",
        source="x_deleted_janitor",
        name="X 已删除推文定期清理",
        schedule=CronSchedule(hour="*/6", minute=11),
        coalesce=True,
        misfire_grace_time=3600,
    ),
    # DailyHot 聚合热榜（编排内网自托管 DailyHotApi）：与其他采集源错开分钟
    CronJobDescriptor(
        id="dailyhot_hotlists",
        source="dailyhot",
        name="DailyHot 聚合热榜采集",
        schedule=CronSchedule(minute=7),
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
        name="GitHub 项目库当天指标每两小时刷新（含新越线项目富化补跑）",
        schedule=CronSchedule(hour="1-23/2", minute=17),
        coalesce=True,
        misfire_grace_time=3600,
    ),
    # 新仓快车道：补上每日全量爬取之间的发现空窗，锁忙即让路。分钟错开
    # 整点各源（:01–:08）与两小时刷新（:17）；错过超过 10 分钟宁可等下一轮。
    CronJobDescriptor(
        id="github_fast_lane",
        source="github_fast_lane",
        name="GitHub 新仓快车道（近 7 天新建越线项目每 15 分钟入库）",
        schedule=CronSchedule(minute="10,25,40,55"),
        coalesce=True,
        misfire_grace_time=600,
    ),
    # ── CST 源关榜采集（次日 00:3x，昨日归属）─────────────────────────
    # 与分源定稿契约对齐：CST 源 01:00 揭榜前，用一轮昨日归属的采集收齐
    # 源日界尾巴（hourly 末轮 23:0x 之后的内容）。misfire 宽限 30 分钟：
    # 迟到超过关榜窗口宁可跳过，绝不写入已定稿切片。
    CronJobDescriptor(
        id="github_project_metrics_closing",
        source="github_project_metrics_closing",
        name="GitHub 项目库指标关榜刷新（昨日切片）",
        schedule=CronSchedule(hour=0, minute=33),
        coalesce=False,
        misfire_grace_time=1800,
    ),
    CronJobDescriptor(
        id="x_closing",
        source="x_closing",
        name="X 关注账号推文关榜采集（昨日归属）",
        schedule=CronSchedule(hour=0, minute=31),
        coalesce=False,
        misfire_grace_time=1800,
    ),
    CronJobDescriptor(
        id="hackernews_closing",
        source="hackernews_closing",
        name="Hacker News 关榜采集（昨日归属）",
        schedule=CronSchedule(hour=0, minute=35),
        coalesce=False,
        misfire_grace_time=1800,
    ),
    CronJobDescriptor(
        id="news_closing",
        source="news_closing",
        name="Techmeme 科技新闻关榜采集（昨日归属）",
        schedule=CronSchedule(hour=0, minute=36),
        coalesce=False,
        misfire_grace_time=1800,
    ),
)

DAILY_BRIEFING_JOB = CronJobDescriptor(
    id="daily_briefing",
    source="daily_briefing",
    name="每日自动简报生成（全维度）",
    schedule=CronSchedule(hour=8, minute=0),
)

# 订阅派发只读简报缓存（不触发生成），每半小时一轮幂等投递：
# daily 消费 8:00 生成任务填充的缓存，weekly/monthly 消费按需生成的缓存；
# 与生成解耦，错过点火合并一次即可（coalesce=True）。
SUBSCRIPTION_DISPATCH_JOB = CronJobDescriptor(
    id="subscription_dispatch",
    source="subscription_dispatch",
    name="订阅简报派发（全频率幂等投递）",
    schedule=CronSchedule(minute="*/30"),
    coalesce=True,
    misfire_grace_time=1800,
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


def x_media_warmup_job_descriptor(*, timezone: str) -> IntervalJobDescriptor:
    """X 媒体边缘缓存预热兜底：采集钩子只管「新数据入库」时刻，nginx 重启 /
    缓存容量驱逐 / 后端重启后的冷缓存靠周期重扫兜底。幂等——边缘 HIT 仅
    毫秒级 localhost 往返，重复预热成本可忽略。"""
    return IntervalJobDescriptor(
        id="x_media_warmup",
        source="x_media_warmup",
        name="X 媒体边缘缓存预热与封面回填",
        schedule=IntervalSchedule(minutes=30),
        timezone=timezone,
    )


CONVERSATION_CLEANUP_JOB = CronJobDescriptor(
    id="conversation_cleanup",
    source="conversation_cleanup",
    name="会话历史定期清理（7 天清 5 条）",
    schedule=CronSchedule(day="*/7", hour=3, minute=30),
)

# 支付订单超时关单：pending 超过 TTL（payments_order_ttl_minutes）即过期，
# 之后回调走 expired→paid 迟到支付特许边（钱已收必须发权益）。5 分钟一轮，
# 单轮限量（仓储侧 limit）防长事务；mark_expired_overdue 是条件更新，
# 重复点火幂等，错过合并一次即可（coalesce=True）。
PAYMENT_ORDER_CLOSING_JOB = IntervalJobDescriptor(
    id="payment_order_closing",
    source="payment_order_closing",
    name="支付订单超时关单（到期 pending → expired）",
    schedule=IntervalSchedule(minutes=5),
    timezone="Asia/Shanghai",
)


UI_LIBRARY_JOBS: tuple[CronJobDescriptor, ...] = (
    CronJobDescriptor(id="ui_library_discovery", source="ui_library_discovery",
        name="UI 素材库每日发现（开源组件与 Codrops）", schedule=CronSchedule(hour=9, minute=0), coalesce=True),
    CronJobDescriptor(id="ui_library_x_discovery", source="ui_library_x_discovery",
        name="UI 素材库设计师 X 新作发现", schedule=CronSchedule(hour=9, minute=10), coalesce=True),
)


def resolve_source_job_callback(
    source: JobSource,
    namespace: Mapping[str, Any],
) -> SchedulerCallback:
    """Resolve a source callback lazily from the scheduler module namespace."""
    callback_name = {
        "ui_library_discovery": "_run_ui_library_discovery_job",
        "ui_library_x_discovery": "_run_ui_library_x_discovery_job",
        "github_project_daily_pipeline": "_run_github_project_daily_pipeline_job",
        "github_project_metrics_refresh": "_run_github_project_metrics_refresh_job",
        "github_project_metrics_closing": "_run_github_project_metrics_closing_job",
        "github_fast_lane": "_run_github_fast_lane_job",
        "x_credentials_probe": "_run_x_credentials_probe_job",
        "x_deleted_janitor": "_run_x_deleted_janitor_job",
        "x_closing": "_run_x_closing_job",
        "hackernews_closing": "_run_hackernews_closing_job",
        "news_closing": "_run_news_closing_job",
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
    if isinstance(descriptor, WindowedIntervalJobDescriptor):
        return DailyWindowIntervalTrigger(
            start_time=descriptor.start_time,
            end_time=descriptor.end_time,
            interval_minutes=descriptor.interval_minutes,
            timezone=descriptor.timezone,
        )
    return IntervalTrigger(
        seconds=descriptor.schedule.seconds,
        minutes=descriptor.schedule.minutes,
        timezone=descriptor.timezone,
    )


def apply_job_config(
    descriptor: JobDescriptor,
    config: Any,
) -> JobDescriptor | None:
    """Return a windowed descriptor when ``config`` overrides ``descriptor``.

    Returns ``None`` when the job is explicitly disabled. All other descriptor
    options (coalesce, misfire grace time, etc.) are copied from the default
    descriptor so behavior stays consistent after an override.
    """
    if not config.enabled:
        return None

    start = config.start_time
    end = config.end_time
    interval = config.interval_minutes

    if isinstance(descriptor, CronJobDescriptor):
        return WindowedIntervalJobDescriptor(
            id=descriptor.id,
            source=descriptor.source,
            name=descriptor.name,
            start_time=start,
            end_time=end,
            interval_minutes=interval,
            timezone=descriptor.timezone,
            replace_existing=descriptor.replace_existing,
            max_instances=descriptor.max_instances,
            coalesce=descriptor.coalesce,
            misfire_grace_time=descriptor.misfire_grace_time,
        )
    if isinstance(descriptor, IntervalJobDescriptor):
        return WindowedIntervalJobDescriptor(
            id=descriptor.id,
            source=descriptor.source,
            name=descriptor.name,
            start_time=start,
            end_time=end,
            interval_minutes=interval,
            timezone=descriptor.timezone,
            replace_existing=descriptor.replace_existing,
            max_instances=descriptor.max_instances,
            coalesce=descriptor.coalesce,
            misfire_grace_time=descriptor.misfire_grace_time,
        )
    # Already windowed: just swap the schedule fields.
    return WindowedIntervalJobDescriptor(
        id=descriptor.id,
        source=descriptor.source,
        name=descriptor.name,
        start_time=start,
        end_time=end,
        interval_minutes=interval,
        timezone=descriptor.timezone,
        replace_existing=descriptor.replace_existing,
        max_instances=descriptor.max_instances,
        coalesce=descriptor.coalesce,
        misfire_grace_time=descriptor.misfire_grace_time,
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
