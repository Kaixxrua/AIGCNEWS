"""IngestionAdminService 手动单源采集串行锁测试。

手动 github/x 采集必须复用调度器的串行锁（与定时任务同一互斥口径），
其余源放行不加锁；未注入锁且调度器未启动时回退为无锁（隔离测试可直连）。
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from backend.app.services.ingestion_admin import IngestionAdminService


def _make_service(**kwargs: Any) -> IngestionAdminService:
    with patch(
        "backend.app.services.ingestion_admin.provide_ingestion_dependencies",
        return_value=MagicMock(),
    ):
        return IngestionAdminService(MagicMock(), **kwargs)


def _patch_pipeline(recorder: dict[str, Any]):
    """替换单源采集入口：记录调用瞬间两把锁的占用状态。"""

    def fake_run_single_source_pipeline(
        source_name: str,
        limit: int = 25,
        top_n: int = 10,
        target_date: str | None = None,
        periods: list[str] | None = None,
        *,
        dependencies: Any = None,
    ) -> dict[str, int]:
        recorder["calls"].append(source_name)
        recorder["locked_at_call"].append(
            (
                recorder["github_lock"].locked(),
                recorder["x_lock"].locked(),
            )
        )
        return {source_name: 1, "ingested_total": 1}

    return patch(
        "backend.app.services.ingestion.pipeline.run_single_source_pipeline",
        fake_run_single_source_pipeline,
    )


class IngestionAdminLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_github_ingest_holds_github_lock(self) -> None:
        github_lock = asyncio.Lock()
        x_lock = asyncio.Lock()
        service = _make_service(github_lock=github_lock, x_lock=x_lock)
        recorder: dict[str, Any] = {
            "calls": [],
            "locked_at_call": [],
            "github_lock": github_lock,
            "x_lock": x_lock,
        }

        with _patch_pipeline(recorder):
            await service.ingest_source("github", 20)

        assert recorder["calls"] == ["github"]
        assert recorder["locked_at_call"] == [(True, False)]

    async def test_x_ingest_holds_x_lock(self) -> None:
        github_lock = asyncio.Lock()
        x_lock = asyncio.Lock()
        service = _make_service(github_lock=github_lock, x_lock=x_lock)
        recorder: dict[str, Any] = {
            "calls": [],
            "locked_at_call": [],
            "github_lock": github_lock,
            "x_lock": x_lock,
        }

        with _patch_pipeline(recorder):
            await service.ingest_source("x", 20)

        assert recorder["calls"] == ["x"]
        assert recorder["locked_at_call"] == [(False, True)]

    async def test_other_sources_bypass_locks(self) -> None:
        github_lock = asyncio.Lock()
        x_lock = asyncio.Lock()
        service = _make_service(github_lock=github_lock, x_lock=x_lock)
        recorder: dict[str, Any] = {
            "calls": [],
            "locked_at_call": [],
            "github_lock": github_lock,
            "x_lock": x_lock,
        }

        with _patch_pipeline(recorder):
            await service.ingest_source("news", 20)
            await service.ingest_source("arxiv", 20)

        assert recorder["calls"] == ["news", "arxiv"]
        assert recorder["locked_at_call"] == [(False, False), (False, False)]

    async def test_concurrent_github_ingests_are_serialized(self) -> None:
        github_lock = asyncio.Lock()
        service = _make_service(github_lock=github_lock)
        order: list[str] = []
        first_entered = asyncio.Event()

        def fake_pipeline(source_name: str, *args: Any, **kwargs: Any) -> dict[str, int]:
            return {source_name: 1, "ingested_total": 1}

        async def slow_first() -> None:
            async with github_lock:
                order.append("scheduled:start")
                first_entered.set()
                await asyncio.sleep(0.05)
                order.append("scheduled:end")

        with patch(
            "backend.app.services.ingestion.pipeline.run_single_source_pipeline",
            fake_pipeline,
        ):
            scheduled = asyncio.create_task(slow_first())
            await first_entered.wait()
            await service.ingest_source("github", 20)
            order.append("manual:end")
            await scheduled

        # 手动采集必须排在持锁的定时任务之后
        assert order == ["scheduled:start", "scheduled:end", "manual:end"]

    async def test_falls_back_to_active_runtime_locks(self) -> None:
        github_lock = asyncio.Lock()
        x_lock = asyncio.Lock()
        runtime = MagicMock()
        runtime.github_job_lock = github_lock
        runtime.x_operation_lock = x_lock
        service = _make_service()  # 未显式注入锁
        recorder: dict[str, Any] = {
            "calls": [],
            "locked_at_call": [],
            "github_lock": github_lock,
            "x_lock": x_lock,
        }

        with (
            patch(
                "backend.app.core.scheduler.get_active_scheduler_runtime",
                return_value=runtime,
            ),
            _patch_pipeline(recorder),
        ):
            await service.ingest_source("github", 20)
            await service.ingest_source("x", 20)

        assert recorder["locked_at_call"] == [(True, False), (False, True)]

    async def test_no_runtime_no_injection_runs_unlocked(self) -> None:
        service = _make_service()
        github_lock = asyncio.Lock()
        x_lock = asyncio.Lock()
        recorder: dict[str, Any] = {
            "calls": [],
            "locked_at_call": [],
            "github_lock": github_lock,
            "x_lock": x_lock,
        }

        with (
            patch(
                "backend.app.core.scheduler.get_active_scheduler_runtime",
                return_value=None,
            ),
            _patch_pipeline(recorder),
        ):
            await service.ingest_source("github", 20)

        assert recorder["calls"] == ["github"]
        assert recorder["locked_at_call"] == [(False, False)]


if __name__ == "__main__":
    unittest.main()
