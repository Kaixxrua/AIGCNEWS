from __future__ import annotations

"""Administrative ingestion command adapters."""

import asyncio
import logging

from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)
from backend.app.services.ingestion.composition import provide_ingestion_dependencies

logger = logging.getLogger(__name__)
VALID_SOURCES = frozenset({"arxiv", "github", "news", "producthunt", "hackernews", "x"})


class IngestionAdminService:
    """Expose ingestion entry points as background-task compatible commands.

    github/x 手动单源采集复用调度器的串行锁（core/scheduler.py 的
    ``_github_job_lock`` / ``_x_operation_lock``），与 dependencies.py 中
    ``get_x_operation_lock`` 的口径一致：运行时未提供锁时回退为无锁，
    保证隔离测试可直接调用；其余源不加串行锁，直接放行。
    """

    def __init__(
        self,
        repositories: ApplicationRepositories,
        *,
        github_lock: asyncio.Lock | None = None,
        x_lock: asyncio.Lock | None = None,
    ) -> None:
        self._repositories = repositories
        self._github_lock = github_lock
        self._x_lock = x_lock
        self._dependencies = provide_ingestion_dependencies(
            repositories=repositories,
        )

    def smart_ingest(self, limit: int) -> None:
        from backend.app.services.ingestion.pipeline import run_smart_ingestion

        run_smart_ingestion(
            limit=limit,
            reader=self._repositories.ingestion_tasks,
            runner=self._run_pipeline,
        )

    def force_ingest(self, limit: int) -> None:
        self._run_pipeline(limit)

    def ingest_by_date(self, target_date: str, limit: int) -> None:
        from backend.app.services.ingestion.pipeline import run_ingestion_pipeline

        logger.info("[Ops] 开始按日期采集：target_date=%s, limit=%d", target_date, limit)
        try:
            result = run_ingestion_pipeline(
                limit=limit,
                target_date=target_date,
                dependencies=self._dependencies,
            )
            ingested = result.get("ingested_total", 0) if isinstance(result, dict) else 0
            logger.info("[Ops] 按日期采集完成：date=%s, ingested=%d", target_date, ingested)
        except Exception:
            logger.exception("[Ops] 按日期采集失败：date=%s", target_date)

    async def ingest_source(self, source_name: str, limit: int) -> None:
        """单源采集：github/x 持串行锁执行，其余源直接执行。

        定义为协函数：ApplicationOperationsRuntime 对协函数直接 await，
        与调度任务在同一事件循环上竞争同一把 asyncio.Lock。
        """
        from backend.app.services.ingestion.pipeline import run_single_source_pipeline

        lock = self._resolve_source_lock(source_name)

        async def _run() -> None:
            await asyncio.to_thread(
                run_single_source_pipeline,
                source_name=source_name,
                limit=limit,
                dependencies=self._dependencies,
            )

        if lock is None:
            await _run()
            return
        async with lock:
            await _run()

    def _resolve_source_lock(self, source_name: str) -> asyncio.Lock | None:
        if source_name == "github":
            injected = self._github_lock
        elif source_name == "x":
            injected = self._x_lock
        else:
            return None
        if injected is not None:
            return injected

        # 构造方未显式注入时，向活动调度运行时借用同一把锁（生产路径）。
        from backend.app.core.scheduler import get_active_scheduler_runtime

        runtime = get_active_scheduler_runtime()
        if runtime is None:
            return None
        return runtime.github_job_lock if source_name == "github" else runtime.x_operation_lock

    def _run_pipeline(self, limit: int):
        from backend.app.services.ingestion.pipeline import run_ingestion_pipeline

        return run_ingestion_pipeline(
            limit=limit,
            dependencies=self._dependencies,
        )
