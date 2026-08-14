from __future__ import annotations

"""x_media_warmup 周期兜底 job 的调度器接线测试，镜像
test_scheduler_project_semantic_warmup.py 的既有模式。
"""

import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.core import scheduler


def _runtime(**overrides) -> scheduler.ApplicationSchedulerRuntime:
    fake_scheduler = MagicMock()
    fake_scheduler.running = False
    fake_scheduler.get_jobs.return_value = []
    kwargs = {
        "scheduler": fake_scheduler,
        "x_media_warmup_enabled": True,
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


class XMediaWarmupJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_job_runs_warmup_cycle_with_documents(self) -> None:
        service = types.ModuleType("backend.app.services.x_media_warmup")
        service.run_x_media_warmup_cycle = AsyncMock()
        repositories = MagicMock()

        with patch.dict(
            sys.modules, {"backend.app.services.x_media_warmup": service}
        ):
            result = await scheduler._run_x_media_warmup_job(repositories)

        self.assertTrue(result)
        service.run_x_media_warmup_cycle.assert_awaited_once_with(
            repositories.documents
        )

    async def test_job_returns_false_on_failure(self) -> None:
        service = types.ModuleType("backend.app.services.x_media_warmup")
        service.run_x_media_warmup_cycle = AsyncMock(
            side_effect=RuntimeError("炸了")
        )
        with patch.dict(
            sys.modules, {"backend.app.services.x_media_warmup": service}
        ):
            result = await scheduler._run_x_media_warmup_job(MagicMock())
        self.assertFalse(result)


class XMediaWarmupRegistrationTests(unittest.TestCase):
    def test_registers_thirty_minute_job_when_enabled(self) -> None:
        runtime, fake_scheduler = _runtime()
        _start(runtime)

        call = next(
            item
            for item in fake_scheduler.add_job.call_args_list
            if item.kwargs.get("id") == "x_media_warmup"
        )
        self.assertEqual(call.kwargs["trigger"].interval.total_seconds(), 1800)
        self.assertEqual(call.kwargs["max_instances"], 1)
        self.assertTrue(call.kwargs["coalesce"])

    def test_not_registered_when_flag_disabled(self) -> None:
        runtime, fake_scheduler = _runtime(x_media_warmup_enabled=False)
        _start(runtime)

        self.assertFalse(
            any(
                item.kwargs.get("id") == "x_media_warmup"
                for item in fake_scheduler.add_job.call_args_list
            )
        )

    def test_suppressed_when_x_source_disabled(self) -> None:
        # x_source_enabled=False 时 X 链路任务整体抑制，预热也不例外
        runtime, fake_scheduler = _runtime(x_source_enabled=False)
        _start(runtime)

        self.assertFalse(
            any(
                item.kwargs.get("id") == "x_media_warmup"
                for item in fake_scheduler.add_job.call_args_list
            )
        )

    def test_resolve_callback_none_when_disabled_for_live_apply(self) -> None:
        # 在线配置尝试启用时，开关关闭必须拿不到 callback
        runtime, _ = _runtime(x_media_warmup_enabled=False)
        from backend.app.core.scheduler_registry import x_media_warmup_job_descriptor

        descriptor = x_media_warmup_job_descriptor(timezone="Asia/Shanghai")
        self.assertIsNone(runtime._resolve_callback(descriptor))
        self.assertIsNone(runtime._base_descriptor("x_media_warmup"))


if __name__ == "__main__":
    unittest.main()
