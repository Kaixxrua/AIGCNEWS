from __future__ import annotations

import unittest
from datetime import time, timedelta
from unittest.mock import MagicMock

from backend.app.core import scheduler
from backend.app.core.scheduler_triggers import DailyWindowIntervalTrigger
from backend.app.services.scheduler_config_admin import SchedulerJobConfigProjection


def _config(
    job_id: str,
    *,
    enabled: bool = True,
    start: time = time(0, 0),
    end: time = time(23, 59),
    interval: int = 30,
) -> SchedulerJobConfigProjection:
    return SchedulerJobConfigProjection(
        job_id=job_id,
        name=job_id,
        start_time=start,
        end_time=end,
        interval_minutes=interval,
        enabled=enabled,
    )


def _runtime(*, running: bool = True, live_job: object | None = None):
    fake_scheduler = MagicMock()
    fake_scheduler.running = running
    fake_scheduler.get_job.return_value = live_job
    runtime = scheduler.ApplicationSchedulerRuntime(
        MagicMock(),
        scheduler=fake_scheduler,
    )
    return runtime, fake_scheduler


class ApplyConfigUpdateTests(unittest.TestCase):
    def test_reschedules_live_job_with_new_trigger(self) -> None:
        runtime, fake_scheduler = _runtime(live_job=MagicMock())

        applied = runtime.apply_config_update(
            _config("arxiv_papers", start=time(6, 0), end=time(22, 0), interval=45)
        )

        self.assertTrue(applied)
        fake_scheduler.reschedule_job.assert_called_once()
        job_id, = fake_scheduler.reschedule_job.call_args.args
        trigger = fake_scheduler.reschedule_job.call_args.kwargs["trigger"]
        self.assertEqual(job_id, "arxiv_papers")
        self.assertIsInstance(trigger, DailyWindowIntervalTrigger)
        self.assertEqual(trigger.start_time, time(6, 0))
        self.assertEqual(trigger.end_time, time(22, 0))
        self.assertEqual(trigger.interval, timedelta(minutes=45))
        fake_scheduler.remove_job.assert_not_called()
        fake_scheduler.add_job.assert_not_called()

    def test_disabling_live_job_removes_it(self) -> None:
        runtime, fake_scheduler = _runtime(live_job=MagicMock())

        applied = runtime.apply_config_update(
            _config("github_trending", enabled=False)
        )

        self.assertTrue(applied)
        fake_scheduler.remove_job.assert_called_once_with("github_trending")
        fake_scheduler.reschedule_job.assert_not_called()

    def test_disabling_absent_job_is_a_no_op_but_applied(self) -> None:
        runtime, fake_scheduler = _runtime(live_job=None)

        applied = runtime.apply_config_update(
            _config("github_trending", enabled=False)
        )

        self.assertTrue(applied)
        fake_scheduler.remove_job.assert_not_called()
        fake_scheduler.add_job.assert_not_called()

    def test_enabling_absent_job_registers_it(self) -> None:
        runtime, fake_scheduler = _runtime(live_job=None)

        applied = runtime.apply_config_update(
            _config("x_watchlist", interval=90)
        )

        self.assertTrue(applied)
        fake_scheduler.add_job.assert_called_once()
        kwargs = fake_scheduler.add_job.call_args.kwargs
        self.assertEqual(kwargs["id"], "x_watchlist")
        self.assertIsInstance(kwargs["trigger"], DailyWindowIntervalTrigger)
        self.assertEqual(kwargs["trigger"].interval, timedelta(minutes=90))

    def test_enabling_absent_daily_briefing_registers_bound_callback(self) -> None:
        runtime, fake_scheduler = _runtime(live_job=None)

        applied = runtime.apply_config_update(_config("daily_briefing"))

        self.assertTrue(applied)
        fake_scheduler.add_job.assert_called_once()
        callback = fake_scheduler.add_job.call_args.args[0]
        self.assertEqual(callback, runtime._run_daily_briefing_job)

    def test_scheduler_not_running_defers_to_next_start(self) -> None:
        runtime, fake_scheduler = _runtime(running=False)

        applied = runtime.apply_config_update(_config("arxiv_papers"))

        self.assertFalse(applied)
        fake_scheduler.reschedule_job.assert_not_called()
        fake_scheduler.remove_job.assert_not_called()
        fake_scheduler.add_job.assert_not_called()
        # 覆盖仍然入库，下次 start() 时生效
        self.assertIn("arxiv_papers", runtime._job_config_overrides)

    def test_unknown_job_is_not_applied(self) -> None:
        runtime, fake_scheduler = _runtime()

        applied = runtime.apply_config_update(_config("no_such_job"))

        self.assertFalse(applied)
        fake_scheduler.reschedule_job.assert_not_called()
        fake_scheduler.add_job.assert_not_called()

    def test_semantic_warmup_ignored_when_feature_disabled(self) -> None:
        runtime, fake_scheduler = _runtime()

        applied = runtime.apply_config_update(_config("project_semantic_warmup"))

        self.assertFalse(applied)
        fake_scheduler.add_job.assert_not_called()

    def test_semantic_warmup_registers_when_feature_enabled(self) -> None:
        fake_scheduler = MagicMock()
        fake_scheduler.running = True
        fake_scheduler.get_job.return_value = None
        runtime = scheduler.ApplicationSchedulerRuntime(
            MagicMock(),
            scheduler=fake_scheduler,
            semantic_search_enabled=True,
        )

        applied = runtime.apply_config_update(
            _config("project_semantic_warmup", interval=15)
        )

        self.assertTrue(applied)
        fake_scheduler.add_job.assert_called_once()
        kwargs = fake_scheduler.add_job.call_args.kwargs
        self.assertEqual(kwargs["id"], "project_semantic_warmup")
        self.assertEqual(kwargs["trigger"].interval, timedelta(minutes=15))

    def test_override_updates_next_start_registration(self) -> None:
        runtime, _ = _runtime()

        runtime.apply_config_update(_config("arxiv_papers", enabled=False))

        override = runtime._job_config_overrides["arxiv_papers"]
        self.assertFalse(override.enabled)


if __name__ == "__main__":
    unittest.main()


class ApplyConfigUpdateXSourceGateTests(unittest.TestCase):
    """x_source_enabled=False 时在线配置被抑制：不注册新任务、移除已在任务。"""

    def _runtime(self, *, live_job: object | None = None):
        fake_scheduler = MagicMock()
        fake_scheduler.running = True
        fake_scheduler.get_job.return_value = live_job
        runtime = scheduler.ApplicationSchedulerRuntime(
            MagicMock(),
            scheduler=fake_scheduler,
            x_source_enabled=False,
        )
        return runtime, fake_scheduler

    def test_enabling_x_job_is_suppressed(self) -> None:
        runtime, fake_scheduler = self._runtime(live_job=None)

        applied = runtime.apply_config_update(_config("x_watchlist"))

        self.assertTrue(applied)
        fake_scheduler.add_job.assert_not_called()
        fake_scheduler.remove_job.assert_not_called()

    def test_suppression_removes_live_x_job(self) -> None:
        runtime, fake_scheduler = self._runtime(live_job=MagicMock())

        applied = runtime.apply_config_update(_config("x_watchlist"))

        self.assertTrue(applied)
        fake_scheduler.remove_job.assert_called_once_with("x_watchlist")
        fake_scheduler.add_job.assert_not_called()

    def test_non_x_job_unaffected_by_x_gate(self) -> None:
        runtime, fake_scheduler = self._runtime(live_job=None)

        applied = runtime.apply_config_update(_config("arxiv_papers"))

        self.assertTrue(applied)
        fake_scheduler.add_job.assert_called_once()
