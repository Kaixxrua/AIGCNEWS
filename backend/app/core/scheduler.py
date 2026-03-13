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

# ═══════════════════════════════════════════════════════════════════════════════
# 调度配置（集中管理所有采集任务的频率）
# ═══════════════════════════════════════════════════════════════════════════════

SCHEDULE_CONFIG: List[Dict[str, Any]] = [
    # ── 高频：实时热榜类 ──────────────────────────────────────────
    {
        "id": "github_trending",
        "source": "github",
        "cron": {"hour": "6,10,14,18,22", "minute": 0},
        "desc": "GitHub Trending 热榜采集",
    },
    {
        "id": "hackernews",
        "source": "hackernews",
        "cron": {"hour": "7,11,15,19,23", "minute": 30},
        "desc": "Hacker News AI 热帖采集",
    },
    {
        "id": "producthunt",
        "source": "producthunt",
        "cron": {"hour": "10,16", "minute": 0},
        "desc": "Product Hunt 新品采集",
    },
    # ── 低频：编辑精选类 ──────────────────────────────────────────
    {
        "id": "arxiv_papers",
        "source": "arxiv",
        "cron": {"hour": "9,15", "minute": 30},
        "desc": "HuggingFace Papers 论文采集",
    },
    {
        "id": "news_techmeme",
        "source": "news",
        "cron": {"hour": "8,12,18", "minute": 0},
        "desc": "Techmeme 科技新闻采集",
    },
    # ── GitHub 热度快照（独立于 Trending，使用 github_hot_service） ──
    {
        "id": "github_hot_refresh",
        "source": "github_hot",
        "cron": {"hour": 2, "minute": 0},
        "desc": "GitHub 热度快照刷新",
    },
]

# 全局 scheduler 实例（单例）
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """获取全局 APScheduler 实例（懒加载）。"""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    return _scheduler


# ═══════════════════════════════════════════════════════════════════════════════
# Job 执行函数
# ═══════════════════════════════════════════════════════════════════════════════


async def _run_single_source_job(source_name: str) -> None:
    """单源采集 Job：在线程池中运行 run_single_source_pipeline。

    Args:
        source_name: 数据源名称（arxiv / github / news / producthunt / hackernews）
    """
    logger.info("[Scheduler] 触发 %s 采集任务...", source_name)
    try:
        from backend.app.services.ingestion.pipeline import run_single_source_pipeline

        result = await asyncio.to_thread(run_single_source_pipeline, source_name)
        ingested = result.get("ingested_total", 0)
        logger.info(
            "[Scheduler] %s 采集完成，入库 %d 条。",
            source_name,
            ingested,
        )
    except Exception as exc:
        logger.error("[Scheduler] %s 采集失败: %s", source_name, exc, exc_info=True)


async def _run_github_hot_job() -> None:
    """GitHub 热度快照 Job：刷新候选池 / Trending / 快照数据。"""
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
    """全量智能采集 Job（向后兼容）：每天 08:00 执行，检测是否需要补录。"""
    logger.info("[Scheduler] 触发每日智能全量采集任务...")
    try:
        from backend.app.services.ingestion.pipeline import run_smart_ingestion

        await asyncio.to_thread(run_smart_ingestion, 20)
        logger.info("[Scheduler] 每日智能全量采集任务完成。")
    except Exception as exc:
        logger.error("[Scheduler] 智能全量采集失败: %s", exc, exc_info=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 调度器生命周期管理
# ═══════════════════════════════════════════════════════════════════════════════


def start_scheduler() -> None:
    """启动 APScheduler，注册所有调度任务。

    任务分两类：
    1. SCHEDULE_CONFIG 中的多源独立调度（按各源自定义频率）
    2. 每日 08:00 全量智能采集（兜底保障，确保至少每天执行一次全量）
    """
    scheduler = get_scheduler()

    if scheduler.running:
        logger.info("[Scheduler] 已在运行，跳过重复启动。")
        return

    # ── 注册多源独立调度任务 ────────────────────────────────────────
    for config in SCHEDULE_CONFIG:
        job_id = config["id"]
        source = config["source"]
        cron = config["cron"]
        desc = config["desc"]

        if source == "github_hot":
            # GitHub 热度快照使用独立函数
            job_func = _run_github_hot_job
        else:
            # 普通数据源使用 run_single_source_pipeline

            # 创建闭包绑定 source_name 避免 late-binding 问题
            async def _make_job(src: str = source) -> None:
                await _run_single_source_job(src)

            job_func = _make_job

        scheduler.add_job(
            job_func,
            trigger=CronTrigger(**cron, timezone="Asia/Shanghai"),
            id=job_id,
            name=desc,
            replace_existing=True,
            max_instances=1,  # 防止同源 job 重叠执行
            misfire_grace_time=7200,  # 允许最多延迟 2 小时触发
        )
        logger.info(
            "[Scheduler] 注册任务: %s (%s) cron=%s",
            job_id,
            desc,
            cron,
        )

    # ── 兜底：每日 08:00 全量智能采集 ──────────────────────────────
    scheduler.add_job(
        _run_smart_ingestion_job,
        trigger=CronTrigger(hour=8, minute=0, timezone="Asia/Shanghai"),
        id="daily_smart_ingestion",
        name="每日全量智能采集（兜底）",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    logger.info("[Scheduler] 注册兜底任务: daily_smart_ingestion (每日 08:00)")

    scheduler.start()

    # 打印完整调度表
    jobs = scheduler.get_jobs()
    logger.info("[Scheduler] APScheduler 已启动，共 %d 个调度任务：", len(jobs))
    for job in jobs:
        logger.info(
            "  📅 %s | %s | 下次执行: %s",
            job.id,
            job.name,
            job.next_run_time,
        )


def stop_scheduler() -> None:
    """优雅停止 APScheduler。"""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[Scheduler] APScheduler 已停止。")


def get_scheduler_status() -> List[Dict[str, Any]]:
    """获取所有调度任务的状态信息（供 API 查询）。

    Returns:
        任务状态列表，每项包含 id/name/next_run_time/trigger 等信息。
    """
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
    """FastAPI lifespan 上下文管理器：启动时开启调度器，关闭时停止。"""
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
