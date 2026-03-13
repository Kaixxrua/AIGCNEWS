from __future__ import annotations

import asyncio
import logging
from datetime import date as DateType
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

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
) -> IngestResponse:
    """
    手动触发数据采集任务。

    - **force=false**（默认）：智能模式，检测落后天数后补录（最多 3 天）。
    - **force=true**：强制模式，直接抓取最新数据，不做日期检测。
    """
    # ── 并发锁：检查是否有任务正在运行 ────────────────────────────────
    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()
    latest = await asyncio.to_thread(db.get_latest_task)
    if latest and latest.get("status") == "running":
        raise HTTPException(
            status_code=409,
            detail="A task is already running. Please wait for it to finish.",
        )

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

    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()
    latest = await asyncio.to_thread(db.get_latest_task)
    if latest and latest.get("status") == "running":
        raise HTTPException(
            status_code=409,
            detail="当前已有任务正在运行，请等待完成后再试。",
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
async def clear_all_data() -> ClearDataResponse:
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
) -> IngestResponse:
    """手动刷新 GitHub 热榜候选池与快照。"""
    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()
    latest = await asyncio.to_thread(db.get_latest_task)
    if latest and latest.get("status") == "running":
        raise HTTPException(
            status_code=409,
            detail="当前已有任务正在运行，请等待完成后再试。",
        )

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

    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()
    latest = await asyncio.to_thread(db.get_latest_task)
    if latest and latest.get("status") == "running":
        raise HTTPException(
            status_code=409,
            detail="当前已有任务正在运行，请等待完成后再试。",
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
async def list_available_sources():
    """返回所有可用的数据源名称列表（前端下拉 / 按钮渲染用）。"""
    return {
        "sources": sorted(_VALID_SOURCES),
    }


@router.get("/ops/scheduler/status", tags=["Ops"])
async def scheduler_status():
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
