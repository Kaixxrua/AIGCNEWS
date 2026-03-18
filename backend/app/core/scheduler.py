from __future__ import annotations

"""智能调度中心（M15 — 多源独立调度）

将单一 cron job 拆分为多任务、多频率的独立调度。
每个数据源可以按照自身特性设置不同的采集频率。

设计原则：
  - 每个数据源独立 APScheduler Job，互不影响
  - 通过 SCHEDULE_CONFIG 集中管理所有调度配置
  - max_instances=1 防止同源 job 重叠执行
  - misfire_grace_time=7200 确保服务重启后追赶执行
  - 保留 run_smart_ingestion() 兼容入口：仍可手动调用全量采集
  - 保留 lifespan_scheduler() 作为 FastAPI 生命周期管理入口
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

SCHEDULE_CONFIG: List[Dict[str, Any]] = [
    {
        "id": "arxiv_papers",
        "source": "arxiv",
        "cron": {"minute": 1},
        "desc": "HuggingFace Papers 论文采集",
    },
    {
        "id": "github_trending",
        "source": "github",
        "cron": {"minute": 2},
        "desc": "GitHub Trending 热榜采集",
    },
    {
        "id": "news_techmeme",
        "source": "news",
        "cron": {"minute": 3},
        "desc": "Techmeme 科技新闻采集",
    },
    {
        "id": "producthunt",
        "source": "producthunt",
        "cron": {"minute": 4},
        "desc": "Product Hunt 新品采集",
    },
    {
        "id": "hackernews",
        "source": "hackernews",
        "cron": {"minute": 5},
        "desc": "Hacker News AI 热帖采集",
    },
    {
        "id": "github_hot_refresh",
        "source": "github_hot",
        "cron": {"hour": 2, "minute": 0},
        "desc": "GitHub 热度快照刷新",
    },
]

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    return _scheduler


async def _run_single_source_job(source_name: str) -> None:
    logger.info("[Scheduler] 触发 %s 采集任务...", source_name)
    try:
        from backend.app.services.ingestion.pipeline import run_single_source_pipeline

        result = await asyncio.to_thread(run_single_source_pipeline, source_name)
        ingested = result.get("ingested_total", 0)
        logger.info("[Scheduler] %s 采集完成，入库 %d 条。", source_name, ingested)
    except Exception as exc:
        logger.error("[Scheduler] %s 采集失败: %s", source_name, exc, exc_info=True)


async def _run_github_hot_job() -> None:
    logger.info("[Scheduler] 触发 GitHub 热度快照刷新...")
    try:
        from backend.app.services.ingestion.github_hot_service import (
            refresh_github_hot_candidates,
        )

        await asyncio.to_thread(refresh_github_hot_candidates, 80)
        logger.info("[Scheduler] GitHub 热度快照刷新完成。")
    except Exception as exc:
        logger.error("[Scheduler] GitHub 热度快照刷新失败: %s", exc, exc_info=True)


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


async def _run_daily_briefing_job() -> None:
    logger.info(
        "[Scheduler] 触发每日自动简报生成（%d 个维度）...", len(_BRIEFING_TASKS)
    )
    from backend.app.services.briefing.daily_briefing import DailyBriefingService

    success = 0
    for task in _BRIEFING_TASKS:
        source = task["source"]
        period = task["period"]
        try:
            service = DailyBriefingService()
            async for _payload in service.stream_generate(
                target_date=None,
                source=source,
                period=period,
                force_regenerate=False,
            ):
                pass
            success += 1
            logger.info("[Scheduler] 简报生成完成: source=%s period=%s", source, period)
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


async def _run_conversation_cleanup_job() -> None:
    logger.info("[Scheduler] 触发会话历史清理任务...")
    try:
        from backend.app.services.chat.conversation_service import ConversationService

        deleted = await asyncio.to_thread(
            ConversationService().cleanup_stale_conversations,
        )
        logger.info("[Scheduler] 会话历史清理完成，删除 %d 条旧会话。", deleted)
    except Exception as exc:
        logger.error("[Scheduler] 会话历史清理失败: %s", exc, exc_info=True)


def start_scheduler() -> None:
    scheduler = get_scheduler()

    if scheduler.running:
        logger.info("[Scheduler] 已在运行，跳过重复启动。")
        return

    for config in SCHEDULE_CONFIG:
        job_id = config["id"]
        source = config["source"]
        cron = config["cron"]
        desc = config["desc"]

        if source == "github_hot":
            job_func = _run_github_hot_job
        else:

            async def _make_job(src: str = source) -> None:
                await _run_single_source_job(src)

            job_func = _make_job

        scheduler.add_job(
            job_func,
            trigger=CronTrigger(**cron, timezone="Asia/Shanghai"),
            id=job_id,
            name=desc,
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=7200,
        )
        logger.info("[Scheduler] 注册采集任务: %s (%s) cron=%s", job_id, desc, cron)

    scheduler.add_job(
        _run_daily_briefing_job,
        trigger=CronTrigger(hour=8, minute=0, timezone="Asia/Shanghai"),
        id="daily_briefing",
        name="每日自动简报生成（全维度）",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    logger.info(
        "[Scheduler] 注册简报任务: daily_briefing (每日 08:00，共 %d 个维度)",
        len(_BRIEFING_TASKS),
    )

    scheduler.add_job(
        _run_conversation_cleanup_job,
        trigger=CronTrigger(day="*/7", hour=3, minute=30, timezone="Asia/Shanghai"),
        id="conversation_cleanup",
        name="会话历史定期清理（7 天清 5 条）",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    logger.info("[Scheduler] 注册会话清理任务: conversation_cleanup (每 7 天 03:30)")

    scheduler.start()

    jobs = scheduler.get_jobs()
    logger.info("[Scheduler] APScheduler 已启动，共 %d 个调度任务：", len(jobs))
    for job in jobs:
        logger.info("  📅 %s | %s | 下次执行: %s", job.id, job.name, job.next_run_time)


def stop_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[Scheduler] APScheduler 已停止。")


def get_scheduler_status() -> List[Dict[str, Any]]:
    scheduler = get_scheduler()
    if not scheduler.running:
        return []

    result = []
    for job in scheduler.get_jobs():
        result.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": (
                    job.next_run_time.isoformat() if job.next_run_time else None
                ),
                "trigger": str(job.trigger),
                "max_instances": job.max_instances,
                "pending": job.pending,
            }
        )
    return result


@asynccontextmanager
async def lifespan_scheduler(app) -> AsyncGenerator[None, None]:  # type: ignore[type-arg]
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
