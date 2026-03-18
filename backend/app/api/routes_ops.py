from __future__ import annotations

import asyncio
import logging
from datetime import date as DateType
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.app.core.auth import RequireAdmin

router = APIRouter()
logger = logging.getLogger(__name__)


class IngestRequest(BaseModel):
    limit: int = 20
    force: bool = False  # True = 忽略日期检测，强制抓取


class IngestResponse(BaseModel):
    status: str
    message: str
    task_id: Optional[int] = None


class IngestByDateRequest(BaseModel):
    target_date: str  # YYYY-MM-DD
    limit: int = 30


class ClearDataResponse(BaseModel):
    status: str
    message: str
    deleted_documents: int
    deleted_tasks: int
    milvus_dropped: bool


# ── 后台任务包装 ─────────────────────────────────────────────────────────────


def _bg_smart_ingest(limit: int) -> None:
    """在线程中运行 run_smart_ingestion（同步函数）。"""
    from backend.app.services.ingestion.pipeline import run_smart_ingestion

    run_smart_ingestion(limit=limit)


def _bg_force_ingest(limit: int) -> None:
    """强制触发一次完整 pipeline，不做日期检测。"""
    from backend.app.services.ingestion.pipeline import run_ingestion_pipeline

    run_ingestion_pipeline(limit=limit)


def _bg_ingest_by_date(target_date: str, limit: int) -> None:
    """按指定日期触发采集（在目标日期范围内的数据）。

    pipeline 内部会自行创建 task 记录，此处直接调用即可。
    """
    import re
    from backend.app.services.ingestion.pipeline import run_ingestion_pipeline

    logger.info("[Ops] 开始按日期采集：target_date=%s, limit=%d", target_date, limit)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", target_date):
        logger.error("[Ops] 日期格式错误：%s", target_date)
        return

    try:
        result = run_ingestion_pipeline(limit=limit, target_date=target_date)
        ingested = result.get("ingested_total", 0) if isinstance(result, dict) else 0
        logger.info("[Ops] 按日期采集完成：date=%s, ingested=%d", target_date, ingested)
    except Exception as exc:
        logger.exception("[Ops] 按日期采集失败：date=%s", target_date)


# 可用的单源名称（与 IngestionOrchestrator 注册的爬虫 source_name 一致）
_VALID_SOURCES = {"arxiv", "github", "news", "producthunt", "hackernews"}


def _bg_single_source_ingest(source_name: str, limit: int) -> None:
    """在线程中运行 run_single_source_pipeline（同步函数）。"""
    from backend.app.services.ingestion.pipeline import run_single_source_pipeline

    run_single_source_pipeline(source_name=source_name, limit=limit)


def _bg_refresh_github_hot(limit: int) -> None:
    """刷新 GitHub 候选池 / Trending / 快照数据。"""
    from backend.app.services.ingestion.github_hot_service import (
        refresh_github_hot_candidates,
    )

    refresh_github_hot_candidates(limit=limit)


# ── 路由 ─────────────────────────────────────────────────────────────────────


@router.post("/ops/ingest", response_model=IngestResponse, tags=["Ops"])
async def trigger_ingest(
    request: IngestRequest,
    background_tasks: BackgroundTasks,
    _: dict = Depends(RequireAdmin),
) -> IngestResponse:
    """
    手动触发数据采集任务。

    - **force=false**（默认）：智能模式，检测落后天数后补录（最多 3 天）。
    - **force=true**：强制模式，直接抓取最新数据，不做日期检测。
    """
    if request.force:
        background_tasks.add_task(_bg_force_ingest, request.limit)
        logger.info("[Ops] 强制采集任务已加入后台队列，limit=%d", request.limit)
        return IngestResponse(
            status="queued",
            message=f"强制采集任务已提交（limit={request.limit}），后台执行中。",
        )
    else:
        background_tasks.add_task(_bg_smart_ingest, request.limit)
        logger.info("[Ops] 智能采集任务已加入后台队列，limit=%d", request.limit)
        return IngestResponse(
            status="queued",
            message=f"智能采集任务已提交（limit={request.limit}），后台执行中。",
        )


@router.post("/ops/ingest-by-date", response_model=IngestResponse, tags=["Ops"])
async def ingest_by_date(
    request: IngestByDateRequest,
    background_tasks: BackgroundTasks,
    _: dict = Depends(RequireAdmin),
) -> IngestResponse:
    """
    按指定日期触发数据采集。

    - **target_date**：目标日期，格式 YYYY-MM-DD。
    - **limit**：每个数据源的抓取数量上限（默认 30）。
    """
    import re

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", request.target_date):
        raise HTTPException(
            status_code=400, detail="target_date 格式错误，应为 YYYY-MM-DD"
        )

    background_tasks.add_task(_bg_ingest_by_date, request.target_date, request.limit)
    logger.info(
        "[Ops] 按日期采集任务已加入后台队列：date=%s, limit=%d",
        request.target_date,
        request.limit,
    )
    return IngestResponse(
        status="queued",
        message=f"按日期采集任务已提交（date={request.target_date}, limit={request.limit}），后台执行中。",
    )


@router.post("/ops/clear-data", response_model=ClearDataResponse, tags=["Ops"])
async def clear_all_data(_: dict = Depends(RequireAdmin)) -> ClearDataResponse:
    """
    清空所有已存储数据：

    - SQLite documents 表
    - SQLite ingestion_tasks 表
    - Milvus Collection（向量索引）

    ⚠️ 此操作不可逆，请谨慎使用。
    """
    from backend.app.repositories.mysql_repo import MySQLRepository
    from backend.app.repositories.milvus_repo import MilvusRepository

    db = MySQLRepository()

    # 1. 清空 SQLite
    deleted_docs = await asyncio.to_thread(db.clear_all_documents)
    deleted_tasks = await asyncio.to_thread(db.clear_all_tasks)
    logger.info(
        "[Ops] 已清空 SQLite：documents=%d, tasks=%d", deleted_docs, deleted_tasks
    )

    # 2. 清空 Milvus
    milvus_ok = False
    try:
        milvus_repo = MilvusRepository()
        milvus_ok = await asyncio.to_thread(milvus_repo.drop_collection)
        logger.info("[Ops] Milvus 集合已删除：%s", milvus_ok)
    except Exception as exc:
        logger.warning("[Ops] Milvus 清空失败（可能尚未初始化）：%s", exc)

    return ClearDataResponse(
        status="success",
        message=f"已清空 {deleted_docs} 条文档、{deleted_tasks} 条任务记录，Milvus 集合{'已删除' if milvus_ok else '清空失败（已跳过）'}。",
        deleted_documents=deleted_docs,
        deleted_tasks=deleted_tasks,
        milvus_dropped=milvus_ok,
    )


@router.post("/ops/github-hot/refresh", response_model=IngestResponse, tags=["Ops"])
async def refresh_github_hot(
    limit: int = Query(default=80, ge=20, le=200),
    background_tasks: BackgroundTasks = None,
    _: dict = Depends(RequireAdmin),
) -> IngestResponse:
    """手动刷新 GitHub 热榜候选池与快照。"""
    assert background_tasks is not None
    background_tasks.add_task(_bg_refresh_github_hot, limit)
    logger.info("[Ops] GitHub 热榜刷新任务已加入后台队列，limit=%d", limit)
    return IngestResponse(
        status="queued",
        message=f"GitHub 热榜刷新任务已提交（limit={limit}），后台执行中。",
    )


@router.post("/ops/ingest-source", response_model=IngestResponse, tags=["Ops"])
async def ingest_single_source(
    source: str = Query(
        ..., description="数据源名称：arxiv / github / news / producthunt / hackernews"
    ),
    limit: int = Query(default=20, ge=5, le=100),
    background_tasks: BackgroundTasks = None,  # type: ignore[assignment]
    _: dict = Depends(RequireAdmin),
) -> IngestResponse:
    """
    按数据源独立采集（单源模式）。

    前端监测页面可为每个数据源提供独立的"采集"按钮，
    调用此接口时仅采集指定源，不影响其他源。

    - **source**：数据源名称（arxiv / github / news / producthunt / hackernews）
    - **limit**：每源最多抓取条数（默认 20）
    """
    source_lower = source.strip().lower()
    if source_lower not in _VALID_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"未知数据源 '{source}'，可选值：{', '.join(sorted(_VALID_SOURCES))}",
        )

    assert background_tasks is not None
    background_tasks.add_task(_bg_single_source_ingest, source_lower, limit)
    logger.info(
        "[Ops] 单源采集任务已加入后台队列：source=%s, limit=%d", source_lower, limit
    )
    return IngestResponse(
        status="queued",
        message=f"「{source_lower}」采集任务已提交（limit={limit}），后台执行中。",
    )


@router.get("/ops/ingest-source/list", tags=["Ops"])
async def list_available_sources(_: dict = Depends(RequireAdmin)):
    """返回所有可用的数据源名称列表（前端下拉 / 按钮渲染用）。"""
    return {
        "sources": sorted(_VALID_SOURCES),
    }


@router.get("/ops/scheduler/status", tags=["Ops"])
async def scheduler_status(_: dict = Depends(RequireAdmin)):
    """查询 APScheduler 当前状态与已注册任务列表。"""
    from backend.app.core.scheduler import get_scheduler

    scheduler = get_scheduler()
    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time.isoformat() if job.next_run_time else None
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": next_run,
                "trigger": str(job.trigger),
            }
        )
    return {
        "running": scheduler.running,
        "jobs": jobs,
        "job_count": len(jobs),
    }


@router.post("/ops/scheduler/trigger", tags=["Ops"])
async def trigger_scheduled_job(
    job_id: str = Query(default="daily_smart_ingestion"),
    _: dict = Depends(RequireAdmin),
):
    """立即触发指定的定时任务（用于调试）。"""
    from backend.app.core.scheduler import get_scheduler

    scheduler = get_scheduler()
    job = scheduler.get_job(job_id)
    if job is None:
        return {"status": "error", "message": f"Job '{job_id}' 不存在。"}

    job.modify(next_run_time=None)
    scheduler.wakeup()
    return {"status": "triggered", "message": f"Job '{job_id}' 已触发执行。"}


# ── 每日简报生成 ─────────────────────────────────────────────────────────────

_BRIEFING_TASKS = [
    {"source": "all", "period": "daily"},
    {"source": "arxiv", "period": "daily"},
    {"source": "github", "period": "daily"},
    {"source": "news", "period": "daily"},
    {"source": "producthunt", "period": "daily"},
    {"source": "hackernews", "period": "daily"},
]


async def _bg_generate_all_briefings(force_regenerate: bool) -> None:
    """后台生成全维度每日简报（与 scheduler 中的逻辑一致）。"""
    from backend.app.services.briefing.daily_briefing import DailyBriefingService

    success = 0
    for task in _BRIEFING_TASKS:
        source = task["source"]
        period = task["period"]
        try:
            service = DailyBriefingService()
            async for _ in service.stream_generate(
                target_date=None,
                source=source,
                period=period,
                force_regenerate=force_regenerate,
            ):
                pass
            success += 1
            logger.info("[Ops] 简报生成完成: source=%s period=%s", source, period)
        except Exception as exc:
            logger.error(
                "[Ops] 简报生成失败: source=%s period=%s error=%s",
                source,
                period,
                exc,
                exc_info=True,
            )
    logger.info("[Ops] 全维度简报生成完毕，%d/%d 成功。", success, len(_BRIEFING_TASKS))


def _run_briefings_sync(force_regenerate: bool) -> None:
    """在线程中运行异步简报生成。"""
    import asyncio

    asyncio.run(_bg_generate_all_briefings(force_regenerate))


@router.post("/ops/briefing/generate-all", response_model=IngestResponse, tags=["Ops"])
async def generate_all_briefings(
    force_regenerate: bool = Query(
        default=True, description="是否强制重新生成（忽略缓存）"
    ),
    background_tasks: BackgroundTasks = None,  # type: ignore[assignment]
    _: dict = Depends(RequireAdmin),
) -> IngestResponse:
    """
    手动触发全维度每日简报生成。

    后台依次生成 all / arxiv / github / news / producthunt / hackernews
    六个维度的今日简报，并持久化到数据库。

    - **force_regenerate=true**（默认）：强制重新生成，忽略已有缓存。
    - **force_regenerate=false**：已生成过则跳过，避免重复消耗 LLM。
    """
    assert background_tasks is not None
    background_tasks.add_task(_run_briefings_sync, force_regenerate)
    logger.info(
        "[Ops] 全维度简报生成任务已加入后台队列，force_regenerate=%s", force_regenerate
    )
    return IngestResponse(
        status="queued",
        message=f"全维度每日简报生成任务已提交（force_regenerate={force_regenerate}），后台执行中。",
    )


@router.post("/ops/cache/clear-dashboard", response_model=IngestResponse, tags=["Ops"])
async def clear_dashboard_cache(_: dict = Depends(RequireAdmin)) -> IngestResponse:
    """手动清除 dashboard Redis 缓存，强制下次请求重新查询数据库。

    使用多种 pattern 兜底，确保 aigc-cache:dashboard:* 等所有相关 key 被删除。
    """
    from fastapi_cache import FastAPICache
    from redis.asyncio import Redis as AsyncRedis

    from backend.app.core.config import settings

    redis_client = AsyncRedis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password or None,
        decode_responses=False,
    )
    total_deleted = 0
    try:
        _raw_prefix = getattr(FastAPICache, "_prefix", "") or ""
        patterns = list(
            dict.fromkeys(
                [
                    "aigc-cache:dashboard:*",
                    f"{_raw_prefix}dashboard:*",
                    "dashboard:*",
                    "*:dashboard:*",
                ]
            )
        )
        for pattern in patterns:
            keys = await redis_client.keys(pattern)
            if keys:
                await redis_client.delete(*keys)
                total_deleted += len(keys)
                logger.info(
                    "[Ops] cache clear: pattern=%r 删除 %d keys", pattern, len(keys)
                )
    finally:
        close_method = getattr(redis_client, "aclose", None)
        if close_method:
            await close_method()
        else:
            await redis_client.close()

    logger.info("[Ops] dashboard cache 清除完成，共删除 %d keys。", total_deleted)
    return IngestResponse(
        status="ok",
        message=f"Dashboard 缓存已清除（共删除 {total_deleted} 个 Redis key），下次请求将重新查询数据库。",
    )
