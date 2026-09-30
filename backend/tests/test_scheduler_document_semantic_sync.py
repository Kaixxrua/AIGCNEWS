from __future__ import annotations

"""document_semantic_sync 周期 job 的调度器接线测试，镜像
test_scheduler_x_media_warmup.py 的既有模式。
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from backend.app.core import scheduler
from backend.app.core.scheduler_registry import document_semantic_sync_job_descriptor


def _runtime(**overrides):
    fake_scheduler = MagicMock()
    fake_scheduler.running = False
    fake_scheduler.get_jobs.return_value = []
    kwargs = {
        "scheduler": fake_scheduler,
        "document_semantic_sync_enabled": True,
    }
    kwargs.update(overrides)
    runtime = scheduler.ApplicationSchedulerRuntime(MagicMock(), **kwargs)
    return runtime, fake_scheduler


def _start(runtime: scheduler.ApplicationSchedulerRuntime) -> None:
    with patch.object(scheduler.asyncio, "get_running_loop") as get_loop:
        def close_coroutine(coroutine):
            coroutine.close()
            return MagicMock()

        get_loop.return_value.create_task.side_effect = close_coroutine
        runtime.start()


def _indexer_module(sync) -> types.ModuleType:
    module = types.ModuleType("backend.app.services.indexing.document_semantic_indexer")
    module.sync_document_semantic_index = sync
    return module


class DocumentSemanticSyncJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_job_runs_sync_with_the_semantic_source(self) -> None:
        sync = MagicMock(return_value={"status": "success", "embedded": 3})
        repositories = MagicMock()
        with patch.dict(sys.modules, {"backend.app.services.indexing.document_semantic_indexer": _indexer_module(sync)}):
            result = await scheduler._run_document_semantic_sync_job(repositories)
        self.assertTrue(result)
        sync.assert_called_once()
        self.assertIs(sync.call_args.kwargs["db"], repositories.document_semantic_sources)
        self.assertGreater(sync.call_args.kwargs["max_embed"], 0)

    async def test_failed_sweep_and_exceptions_report_false(self) -> None:
        for sync in (MagicMock(return_value={"status": "failed"}), MagicMock(side_effect=RuntimeError("milvus down"))):
            with self.subTest(sync=sync):
                with patch.dict(sys.modules, {"backend.app.services.indexing.document_semantic_indexer": _indexer_module(sync)}):
                    self.assertFalse(await scheduler._run_document_semantic_sync_job(MagicMock()))

    async def test_missing_source_repository_is_skipped(self) -> None:
        repositories = MagicMock()
        repositories.document_semantic_sources = None
        self.assertFalse(await scheduler._run_document_semantic_sync_job(repositories))


class DocumentSemanticSyncRegistrationTests(unittest.TestCase):
    def test_registers_thirty_minute_job_when_enabled(self) -> None:
        runtime, fake_scheduler = _runtime()
        _start(runtime)
        call = next(item for item in fake_scheduler.add_job.call_args_list if item.kwargs.get("id") == "document_semantic_sync")
        self.assertEqual(call.kwargs["trigger"].interval.total_seconds(), 1800)
        self.assertEqual(call.kwargs["max_instances"], 1)
        self.assertTrue(call.kwargs["coalesce"])

    def test_not_registered_when_flag_disabled(self) -> None:
        runtime, fake_scheduler = _runtime(document_semantic_sync_enabled=False)
        _start(runtime)
        self.assertFalse(any(item.kwargs.get("id") == "document_semantic_sync" for item in fake_scheduler.add_job.call_args_list))

    def test_live_apply_cannot_enable_when_flag_disabled(self) -> None:
        runtime, _ = _runtime(document_semantic_sync_enabled=False)
        descriptor = document_semantic_sync_job_descriptor(timezone="Asia/Shanghai")
        self.assertIsNone(runtime._resolve_callback(descriptor))
        self.assertIsNone(runtime._base_descriptor("document_semantic_sync"))

    def test_create_runtime_reads_the_indexing_flag(self) -> None:
        from backend.app.core.config import settings

        with patch.object(settings, "document_semantic_indexing_enabled", True):
            runtime = scheduler.create_scheduler_runtime(MagicMock(), enabled=False)
        self.assertTrue(runtime._document_semantic_sync_enabled)


if __name__ == "__main__":
    unittest.main()
