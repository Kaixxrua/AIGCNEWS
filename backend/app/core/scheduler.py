from __future__ import annotations

"""智能调度中心（M15 — 多源独立调度）

将单一 cron job 拆分为多任务、多频率的独立调度。
每个数据源可以按照自身特性设置不同的采集频率。

设计原则：
  - 每个数据源独立 APScheduler Job，互不影响
  - 通过不可变任务描述符集中管理所有调度配置
  - max_instances=1 防止同源 job 重叠执行
  - misfire_grace_time=7200 确保服务重启后追赶执行
  - 保留 run_smart_ingestion() 兼容入口：仍可手动调用全量采集
  - 保留 lifespan_scheduler() 作为 FastAPI 生命周期管理入口
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Dict, List

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.app.core.scheduler_registry import (
    CONVERSATION_CLEANUP_JOB,
    DAILY_BRIEFING_JOB,
    SOURCE_JOB_DESCRIPTORS,
    JobDescriptor,
    SchedulerCallback,
    build_trigger,
    project_scheduler_status,
    project_semantic_warmup_job_descriptor,
    resolve_source_job_callback,
)
from backend.app.repositories.application_repository_context import (
    get_configured_application_repositories,
)
from backend.app.repositories.briefing_repository import ActiveBriefingSubscriberReader
from backend.app.repositories.conversation_repository import ConversationCleanupWriter
from backend.app.repositories.rank_snapshot_repository import RankSnapshotRepository

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_github_job_lock: asyncio.Lock | None = None
_startup_reconciliation_tasks: set[asyncio.Task[Any]] = set()
_ARXIV_RECONCILE_DAYS = 2
_GITHUB_METRICS_REFRESH_LIMIT = 0  # 0 表示刷新全部符合条件的项目
_GITHUB_METRICS_MIN_STARS = 500
_GITHUB_METRICS_MAX_AGE = timedelta(hours=2, minutes=15)


def _get_github_job_lock() -> asyncio.Lock:
    global _github_job_lock
    if _github_job_lock is None:
        _github_job_lock = asyncio.Lock()
    return _github_job_lock


def _missing_recent_arxiv_daily_dates(
    rank_snapshots: RankSnapshotRepository | None = None,
) -> List[str]:
    """Return missing recent HF daily dates, bounded to avoid startup storms."""
    from backend.app.services.ingestion.base_crawler import today_cst

    repository = (
        rank_snapshots
        or get_configured_application_repositories().rank_snapshots
    )
    today = date.fromisoformat(today_cst())
    candidates = [
        (today - timedelta(days=offset)).isoformat()
        for offset in range(_ARXIV_RECONCILE_DAYS, 0, -1)
    ]
    existing = set(
        repository.get_snapshot_dates(
            limit=_ARXIV_RECONCILE_DAYS,
            source="arxiv",
            period="daily",
        )
    )
    return [candidate for candidate in candidates if candidate not in existing]


async def _reconcile_recent_arxiv_daily_snapshots() -> None:
    try:
        missing_dates = await asyncio.to_thread(_missing_recent_arxiv_daily_dates)
    except Exception as exc:
        logger.warning("[Scheduler] 检查 Arxiv 日榜缺口失败，跳过启动补齐: %s", exc)
        return

    for target_date in missing_dates:
        logger.info("[Scheduler] 补齐缺失 Arxiv 日榜快照: %s", target_date)
        try:
            from backend.app.services.ingestion.pipeline import run_single_source_pipeline

            await asyncio.to_thread(
                run_single_source_pipeline,
                "arxiv",
                target_date=target_date,
                periods=["daily"],
            )
        except Exception as exc:
            logger.error("[Scheduler] Arxiv 日榜快照补齐失败 %s: %s", target_date, exc)


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    return _scheduler


async def _run_single_source_job(source_name: str) -> None:
    logger.info("[Scheduler] 触发 %s 采集任务...", source_name)
    lock = _get_github_job_lock() if source_name == "github" else None
    try:
        from backend.app.services.ingestion.pipeline import run_single_source_pipeline

        if lock is None:
            result = await asyncio.to_thread(run_single_source_pipeline, source_name)
        else:
            async with lock:
                result = await asyncio.to_thread(run_single_source_pipeline, source_name)
        ingested = result.get("ingested_total", 0)
        logger.info("[Scheduler] %s 采集完成，入库 %d 条。", source_name, ingested)
    except Exception as exc:
        logger.error("[Scheduler] %s 采集失败: %s", source_name, exc, exc_info=True)


async def _run_github_project_daily_pipeline_job() -> None:
    logger.info("[Scheduler] 触发 GitHub 项目库每日流水线...")
    try:
        from backend.app.services.ingestion.github_project_enricher import (
            run_github_project_daily_pipeline,
        )

        async with _get_github_job_lock():
            result = await asyncio.to_thread(
                run_github_project_daily_pipeline,
                refresh_limit=80,
                enrich_limit=50,
            )
        logger.info("[Scheduler] GitHub 项目库每日流水线完成：%s", result)
    except Exception as exc:
        logger.error("[Scheduler] GitHub 项目库每日流水线失败: %s", exc, exc_info=True)


def _github_refresh_needed(status: Dict[str, Any]) -> bool:
    target_count = int(status.get("target_count") or 0)
    if target_count == 0:
        return False
    if int(status.get("snapshot_count") or 0) < target_count:
        return True
    if int(status.get("metric_count") or 0) < target_count:
        return True

    latest = status.get("oldest_captured_at")
    if not latest:
        return True
    if isinstance(latest, str):
        try:
            latest = datetime.fromisoformat(latest.replace("Z", "+00:00"))
        except ValueError:
            return True
    if not isinstance(latest, datetime):
        return True
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - latest.astimezone(timezone.utc) > _GITHUB_METRICS_MAX_AGE


async def _refresh_current_github_project_metrics(metric_date: str) -> Dict[str, Any]:
    from backend.app.services.ingestion.github_project_metrics_service import (
        refresh_and_compute_github_project_metrics,
    )

    repositories = get_configured_application_repositories()
    return await asyncio.to_thread(
        refresh_and_compute_github_project_metrics,
        min_stars=_GITHUB_METRICS_MIN_STARS,
        limit=_GITHUB_METRICS_REFRESH_LIMIT,
        metric_date=metric_date,
        db=repositories.github_ingestion,
    )


async def _run_github_project_metrics_refresh_job() -> None:
    from backend.app.services.ingestion.github_project_metrics_service import (
        current_github_metric_date,
    )

    metric_date = current_github_metric_date()
    logger.info("[Scheduler] 触发 GitHub 当天指标刷新: %s", metric_date)
    try:
        async with _get_github_job_lock():
            result = await _refresh_current_github_project_metrics(metric_date)
        logger.info("[Scheduler] GitHub 当天指标刷新完成：%s", result)
    except Exception as exc:
        logger.error("[Scheduler] GitHub 当天指标刷新失败: %s", exc, exc_info=True)


async def _reconcile_current_github_project_metrics() -> None:
    from backend.app.services.ingestion.github_project_metrics_service import (
        current_github_metric_date,
    )

    metric_date = current_github_metric_date()
    try:
        repository = get_configured_application_repositories().github_ingestion
        async with _get_github_job_lock():
            status = await asyncio.to_thread(
                repository.get_github_metric_refresh_status,
                metric_date=metric_date,
                min_stars=_GITHUB_METRICS_MIN_STARS,
                limit=_GITHUB_METRICS_REFRESH_LIMIT,
            )
            if not _github_refresh_needed(status):
                logger.info("[Scheduler] GitHub 当天指标完整且新鲜，跳过启动补跑：%s", status)
                return
            logger.info("[Scheduler] GitHub 当天指标缺失或过期，执行启动补跑：%s", status)
            await _refresh_current_github_project_metrics(metric_date)
    except Exception as exc:
        logger.warning("[Scheduler] GitHub 当天指标启动补跑失败: %s", exc, exc_info=True)


async def _run_github_hot_job() -> None:
    logger.info("[Scheduler] 触发 GitHub 热度快照刷新...")
    try:
        from backend.app.services.ingestion.github_hot_service import (
            refresh_github_hot_candidates,
        )

        repository = get_configured_application_repositories().github_ingestion
        await asyncio.to_thread(
            refresh_github_hot_candidates,
            80,
            db=repository,
        )
        logger.info("[Scheduler] GitHub 热度快照刷新完成。")
    except Exception as exc:
        logger.error("[Scheduler] GitHub 热度快照刷新失败: %s", exc, exc_info=True)


async def _run_github_project_enrichment_job() -> None:
    logger.info("[Scheduler] 触发 GitHub 项目库 AI 分类富化...")
    try:
        from backend.app.services.ingestion.github_project_enricher import (
            enrich_github_projects,
        )

        repository = get_configured_application_repositories().github_enrichment
        result = await asyncio.to_thread(
            enrich_github_projects,
            limit=50,
            db=repository,
        )
        logger.info("[Scheduler] GitHub 项目库 AI 分类富化完成：%s", result)
    except Exception as exc:
        logger.error("[Scheduler] GitHub 项目库 AI 分类富化失败: %s", exc, exc_info=True)


async def _run_smart_ingestion_job() -> None:
    logger.info("[Scheduler] 触发智能全量采集任务...")
    try:
        from backend.app.services.ingestion.pipeline import run_smart_ingestion

        await asyncio.to_thread(run_smart_ingestion, 20)
        logger.info("[Scheduler] 智能全量采集任务完成。")
    except Exception as exc:
        logger.error("[Scheduler] 智能全量采集失败: %s", exc, exc_info=True)


_BRIEFING_TASKS: List[Dict[str, str]] = [
    {"source": "all", "period": "daily"},
    {"source": "arxiv", "period": "daily"},
    {"source": "github", "period": "daily"},
    {"source": "news", "period": "daily"},
    {"source": "producthunt", "period": "daily"},
    {"source": "hackernews", "period": "daily"},
]


async def _send_briefing_to_subscribers(
    *,
    source: str,
    period: str,
    date_str: str,
    content: str,
    subscriptions: ActiveBriefingSubscriberReader | None = None,
) -> int:
    from backend.app.services.email_service import build_email_service

    repository = (
        subscriptions
        or get_configured_application_repositories().briefing_subscriptions
    )
    subscribers = repository.get_active_subscribers(source=source, period=period)
    if not subscribers:
        return 0

    email_svc = build_email_service(None)

    sent = 0
    for subscriber in subscribers:
        email = subscriber.get("email")
        if not email:
            continue
        try:
            await email_svc.send_briefing(
                to_email=email,
                briefing_content=content,
                source=source,
                period=period,
                date_str=date_str,
            )
            sent += 1
        except Exception as exc:
            logger.error(
                "[Scheduler] 订阅简报发送失败: source=%s period=%s email=%s error=%s",
                source,
                period,
                email,
                exc,
                exc_info=True,
            )
    return sent


async def _run_daily_briefing_job() -> None:
    logger.info(
        "[Scheduler] 触发每日自动简报生成（%d 个维度）...", len(_BRIEFING_TASKS)
    )
    from backend.app.services.briefing.composition import provide_daily_briefing_service

    service = provide_daily_briefing_service()
    success = 0
    for task in _BRIEFING_TASKS:
        source = task["source"]
        period = task["period"]
        try:
            content_parts: list[str] = []
            report_date = ""
            briefing_id = -1
            async for payload in service.stream_generate(
                target_date=None,
                source=source,
                period=period,
                force_regenerate=False,
                generate_bilingual=True,
            ):
                payload_type = payload.get("type")
                if payload_type == "start":
                    data = payload.get("data") or {}
                    report_date = str(data.get("date") or "")
                elif payload_type == "content":
                    content_parts.append(str(payload.get("data") or ""))
                elif payload_type == "done":
                    data = payload.get("data") or {}
                    briefing_id = int(data.get("briefing_id") or -1)
            success += 1
            logger.info(
                "[Scheduler] 日报生成完成，准备推送订阅用户: source=%s period=%s",
                source,
                period,
            )
            content = "".join(content_parts)
            if briefing_id > 0 and content.strip() and report_date:
                sent = await _send_briefing_to_subscribers(
                    source=source,
                    period=period,
                    date_str=report_date,
                    content=content,
                )
                logger.info(
                    "[Scheduler] 订阅简报发送完成: source=%s period=%s sent=%d",
                    source,
                    period,
                    sent,
                )
        except Exception as exc:
            logger.error(
                "[Scheduler] 简报生成失败: source=%s period=%s error=%s",
                source,
                period,
                exc,
                exc_info=True,
            )

    logger.info(
        "[Scheduler] 每日简报生成完毕，%d/%d 成功。", success, len(_BRIEFING_TASKS)
    )


async def _run_project_semantic_warmup_job() -> None:
    try:
        from backend.app.services.project_semantic_search import (
            warmup_project_semantic_search,
        )

        result = await asyncio.to_thread(warmup_project_semantic_search)
        if result.get("status") == "failed":
            logger.warning("[Scheduler] 项目语义搜索预热失败：%s", result)
        else:
            logger.info("[Scheduler] 项目语义搜索预热完成：%s", result)
    except Exception as exc:
        logger.warning("[Scheduler] 项目语义搜索预热失败: %s", exc)


def _get_default_conversation_repository() -> ConversationCleanupWriter:
    """Return the configured conversation cleanup repository."""
    return get_configured_application_repositories().conversations


async def _run_conversation_cleanup_job(
    conversation_repository: ConversationCleanupWriter | None = None,
) -> None:
    logger.info("[Scheduler] 触发会话历史清理任务...")
    try:
        from backend.app.services.chat.conversation_service import ConversationService

        repository = (
            _get_default_conversation_repository()
            if conversation_repository is None
            else conversation_repository
        )
        deleted = await asyncio.to_thread(
            ConversationService(repository).cleanup_stale_conversations,
        )
        logger.info("[Scheduler] 会话历史清理完成，删除 %d 条旧会话。", deleted)
    except Exception as exc:
        logger.error("[Scheduler] 会话历史清理失败: %s", exc, exc_info=True)


def _register_job(
    scheduler: AsyncIOScheduler,
    descriptor: JobDescriptor,
    callback: SchedulerCallback,
) -> None:
    job_kwargs: Dict[str, Any] = {
        "trigger": build_trigger(descriptor),
        "id": descriptor.id,
        "name": descriptor.name,
        "replace_existing": descriptor.replace_existing,
        "max_instances": descriptor.max_instances,
        "misfire_grace_time": descriptor.misfire_grace_time,
    }
    if descriptor.coalesce is not None:
        job_kwargs["coalesce"] = descriptor.coalesce
    scheduler.add_job(callback, **job_kwargs)


def start_scheduler() -> None:
    scheduler = get_scheduler()

    if scheduler.running:
        logger.info("[Scheduler] 已在运行，跳过重复启动。")
        return

    for descriptor in SOURCE_JOB_DESCRIPTORS:
        _register_job(
            scheduler,
            descriptor,
            resolve_source_job_callback(descriptor.source, globals()),
        )
        logger.info(
            "[Scheduler] 注册采集任务: %s (%s) cron=%s",
            descriptor.id,
            descriptor.name,
            descriptor.schedule.as_kwargs(),
        )

    _register_job(
        scheduler,
        DAILY_BRIEFING_JOB,
        globals()["_run_daily_briefing_job"],
    )
    logger.info(
        "[Scheduler] 注册简报任务: daily_briefing (每日 08:00，共 %d 个维度)",
        len(_BRIEFING_TASKS),
    )

    from backend.app.core.config import settings

    if settings.project_semantic_search_enabled:
        _register_job(
            scheduler,
            project_semantic_warmup_job_descriptor(
                timezone=settings.scheduler_timezone,
            ),
            globals()["_run_project_semantic_warmup_job"],
        )
        logger.info("[Scheduler] 注册项目语义搜索预热任务（每 30 分钟）")

    _register_job(
        scheduler,
        CONVERSATION_CLEANUP_JOB,
        globals()["_run_conversation_cleanup_job"],
    )
    logger.info("[Scheduler] 注册会话清理任务: conversation_cleanup (每 7 天 03:30)")

    scheduler.start()
    loop = asyncio.get_running_loop()
    for coroutine in (
        _reconcile_recent_arxiv_daily_snapshots(),
        _reconcile_current_github_project_metrics(),
    ):
        task = loop.create_task(coroutine)
        _startup_reconciliation_tasks.add(task)
        task.add_done_callback(_startup_reconciliation_tasks.discard)

    jobs = scheduler.get_jobs()
    logger.info("[Scheduler] APScheduler 已启动，共 %d 个调度任务：", len(jobs))
    for job in jobs:
        logger.info("  📅 %s | %s | 下次执行: %s", job.id, job.name, job.next_run_time)


def stop_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[Scheduler] APScheduler 已停止。")
    for task in tuple(_startup_reconciliation_tasks):
        if not task.done():
            task.cancel()
    _startup_reconciliation_tasks.clear()


def get_scheduler_status() -> List[Dict[str, Any]]:
    scheduler = get_scheduler()
    if not scheduler.running:
        return []

    return project_scheduler_status(scheduler.get_jobs())


@asynccontextmanager
async def lifespan_scheduler(app) -> AsyncGenerator[None, None]:  # type: ignore[type-arg]
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
