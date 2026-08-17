"""GitHub 调度锁保底机制测试（2026-08-17 富化悬挂锁死事故后引入）。

覆盖：
  - _acquire_job_lock：等锁超时返回 False；GitHub 锁超时顺带请求富化批次
    终止（推动持有方自愈），X 锁不触发；
  - _run_single_source_job：锁被悬挂持有时采集任务响亮失败（False），
    不再无限期阻塞；
  - _run_github_project_metrics_refresh_job：富化补跑超过整体封顶时放锁、
    请求批次终止，且指标刷新结果不受影响（任务仍返回 True）；
  - _run_github_project_daily_pipeline_job：流水线超过整体封顶时返回
    False 并请求批次终止。
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.core import scheduler


class AcquireJobLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_returns_false_and_pokes_enrichment_cancel(self) -> None:
        lock = asyncio.Lock()
        await lock.acquire()
        try:
            with (
                patch.object(scheduler, "_JOB_LOCK_WAIT_TIMEOUT", 0.05),
                patch.object(
                    scheduler, "_cancel_github_enrichment_safely"
                ) as cancel,
            ):
                ok = await scheduler._acquire_job_lock(
                    lock,
                    job_label="github 采集",
                    release_stuck_enrichment=True,
                )
        finally:
            lock.release()

        self.assertFalse(ok)
        cancel.assert_called_once_with()

    async def test_timeout_without_enrichment_flag_does_not_poke(self) -> None:
        lock = asyncio.Lock()
        await lock.acquire()
        try:
            with (
                patch.object(scheduler, "_JOB_LOCK_WAIT_TIMEOUT", 0.05),
                patch.object(
                    scheduler, "_cancel_github_enrichment_safely"
                ) as cancel,
            ):
                ok = await scheduler._acquire_job_lock(lock, job_label="x 测活")
        finally:
            lock.release()

        self.assertFalse(ok)
        cancel.assert_not_called()

    async def test_free_lock_acquires_immediately(self) -> None:
        lock = asyncio.Lock()
        ok = await scheduler._acquire_job_lock(lock, job_label="github 采集")
        self.assertTrue(ok)
        self.assertTrue(lock.locked())
        lock.release()


class SingleSourceJobLockGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_github_ingestion_fails_loudly_when_lock_wedged(self) -> None:
        lock = asyncio.Lock()
        await lock.acquire()
        composition_module = types.ModuleType(
            "backend.app.services.ingestion.composition"
        )
        composition_module.provide_ingestion_dependencies = MagicMock(
            return_value=MagicMock()
        )
        pipeline_module = types.ModuleType(
            "backend.app.services.ingestion.pipeline"
        )
        pipeline_module.run_single_source_pipeline = MagicMock()
        try:
            with (
                patch.object(scheduler, "_JOB_LOCK_WAIT_TIMEOUT", 0.05),
                patch.object(
                    scheduler, "_cancel_github_enrichment_safely"
                ) as cancel,
                patch.dict(
                    sys.modules,
                    {
                        "backend.app.services.ingestion.composition": composition_module,
                        "backend.app.services.ingestion.pipeline": pipeline_module,
                    },
                ),
            ):
                started = time.monotonic()
                ok = await scheduler._run_single_source_job(
                    "github",
                    repositories=MagicMock(),
                    github_lock=lock,
                )
                elapsed = time.monotonic() - started
        finally:
            lock.release()

        self.assertFalse(ok)
        self.assertLess(elapsed, 2.0)
        cancel.assert_called_once_with()
        pipeline_module.run_single_source_pipeline.assert_not_called()


class MetricsRefreshTopUpCapTests(unittest.IsolatedAsyncioTestCase):
    async def test_top_up_timeout_releases_lock_but_keeps_refresh_result(self) -> None:
        lock = asyncio.Lock()

        async def _hung_top_up(_: object) -> dict[str, object]:
            await asyncio.sleep(30)
            return {"succeeded": 0}  # pragma: no cover - 永远不会到达

        with (
            patch(
                "backend.app.services.ingestion.github_project_metrics_service."
                "current_github_metric_date",
                return_value="2026-08-17",
            ),
            patch.object(
                scheduler,
                "_refresh_current_github_project_metrics",
                new=AsyncMock(return_value={"refreshed": 10}),
            ) as refresh,
            patch.object(
                scheduler,
                "_enrich_newly_eligible_github_projects",
                side_effect=_hung_top_up,
            ),
            patch.object(scheduler, "_GITHUB_ENRICH_TOP_UP_TIMEOUT", 0.05),
            patch.object(
                scheduler, "_cancel_github_enrichment_safely"
            ) as cancel,
        ):
            started = time.monotonic()
            ok = await scheduler._run_github_project_metrics_refresh_job(
                repository=MagicMock(),
                enrichment=MagicMock(),
                github_lock=lock,
            )
            elapsed = time.monotonic() - started

        self.assertTrue(ok)
        self.assertLess(elapsed, 5.0)
        self.assertFalse(lock.locked())
        refresh.assert_awaited_once()
        cancel.assert_called_once_with()


class DailyPipelineCapTests(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_timeout_fails_loudly_and_pokes_cancel(self) -> None:
        lock = asyncio.Lock()
        stop = threading.Event()

        def _hung_pipeline(**_: object) -> dict[str, object]:
            stop.wait(30)
            return {"status": "ok"}  # pragma: no cover - 测试结束才放行

        enricher_module = types.ModuleType(
            "backend.app.services.ingestion.github_project_enricher"
        )
        enricher_module.run_github_project_daily_pipeline = MagicMock(
            side_effect=_hung_pipeline
        )
        try:
            with (
                patch.object(scheduler, "_GITHUB_DAILY_PIPELINE_TIMEOUT", 0.05),
                patch.object(
                    scheduler, "_cancel_github_enrichment_safely"
                ) as cancel,
                patch.dict(
                    sys.modules,
                    {
                        "backend.app.services.ingestion.github_project_enricher": enricher_module,
                    },
                ),
            ):
                started = time.monotonic()
                ok = await scheduler._run_github_project_daily_pipeline_job(
                    repositories=MagicMock(),
                    github_lock=lock,
                )
                elapsed = time.monotonic() - started
        finally:
            stop.set()

        self.assertFalse(ok)
        self.assertLess(elapsed, 5.0)
        self.assertFalse(lock.locked())
        cancel.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
