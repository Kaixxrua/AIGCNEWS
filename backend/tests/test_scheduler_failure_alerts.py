"""调度器连续失败去抖告警测试。

覆盖：
  - _ConsecutiveFailureAlerter：到达阈值告警一次、不为每次失败重复告警、
    成功后重置计数、重置后再次连续失败可重新告警；
  - ApplicationSchedulerRuntime._guarded：把 job 返回的 False / 未预期异常
    计入连续失败，成功则重置。
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.core import scheduler
from backend.app.core.scheduler import (
    ApplicationSchedulerRuntime,
    _ConsecutiveFailureAlerter,
)


class ConsecutiveFailureAlerterTests(unittest.TestCase):
    def test_alerts_exactly_once_at_threshold(self) -> None:
        calls: list[tuple[str, int, str]] = []
        alerter = _ConsecutiveFailureAlerter(
            threshold=3,
            notifier=lambda job_id, count, detail: calls.append((job_id, count, detail)),
        )

        for _ in range(2):
            alerter.record_failure("github_trending", "boom")
        assert calls == []

        alerter.record_failure("github_trending", "boom")
        assert calls == [("github_trending", 3, "boom")]

        # 第 4、5 次连续失败不再重复发邮件
        alerter.record_failure("github_trending", "boom")
        alerter.record_failure("github_trending", "boom")
        assert calls == [("github_trending", 3, "boom")]

    def test_success_resets_and_threshold_reararms(self) -> None:
        calls: list[tuple[str, int, str]] = []
        alerter = _ConsecutiveFailureAlerter(
            threshold=2,
            notifier=lambda job_id, count, detail: calls.append((job_id, count, detail)),
        )

        alerter.record_failure("job", "e1")
        alerter.record_success("job")  # 成功一次 → 计数清零
        alerter.record_failure("job", "e2")
        assert calls == []  # 未连续到阈值

        alerter.record_failure("job", "e3")
        assert calls == [("job", 2, "e3")]

        alerter.record_success("job")
        alerter.record_failure("job", "e4")
        alerter.record_failure("job", "e5")
        assert calls == [("job", 2, "e3"), ("job", 2, "e5")]

    def test_threshold_one_alerts_on_first_failure(self) -> None:
        calls: list[tuple[str, int, str]] = []
        alerter = _ConsecutiveFailureAlerter(
            threshold=1,
            notifier=lambda job_id, count, detail: calls.append((job_id, count, detail)),
        )
        alerter.record_failure("job", "e")
        assert calls == [("job", 1, "e")]

    def test_notifier_exception_is_swallowed(self) -> None:
        def broken(job_id: str, count: int, detail: str) -> None:
            raise RuntimeError("smtp down")

        alerter = _ConsecutiveFailureAlerter(threshold=1, notifier=broken)
        alerter.record_failure("job", "e")  # 不抛出

    def test_jobs_tracked_independently(self) -> None:
        calls: list[str] = []
        alerter = _ConsecutiveFailureAlerter(
            threshold=2,
            notifier=lambda job_id, count, detail: calls.append(job_id),
        )
        alerter.record_failure("a")
        alerter.record_failure("b")
        alerter.record_failure("b")
        assert calls == ["b"]


class GuardedJobAlertTests(unittest.IsolatedAsyncioTestCase):
    def _runtime(self, calls: list[tuple[str, int, str]]) -> ApplicationSchedulerRuntime:
        return ApplicationSchedulerRuntime(
            MagicMock(),
            scheduler=MagicMock(running=False),
            alert_failure_threshold=3,
            alert_notifier=lambda job_id, count, detail: calls.append((job_id, count, detail)),
        )

    async def test_false_outcome_counts_failure_and_alerts_at_threshold(self) -> None:
        calls: list[tuple[str, int, str]] = []
        runtime = self._runtime(calls)

        async def failing() -> bool:
            return False

        for _ in range(2):
            await runtime._guarded("daily_briefing", failing)
        assert calls == []

        await runtime._guarded("daily_briefing", failing)
        assert len(calls) == 1
        assert calls[0][0] == "daily_briefing"
        assert calls[0][1] == 3

    async def test_success_outcome_resets_counter(self) -> None:
        calls: list[tuple[str, int, str]] = []
        runtime = self._runtime(calls)

        async def failing() -> bool:
            return False

        async def ok() -> bool:
            return True

        await runtime._guarded("job", failing)
        await runtime._guarded("job", failing)
        await runtime._guarded("job", ok)
        await runtime._guarded("job", failing)
        await runtime._guarded("job", failing)
        assert calls == []  # 重置后未再连续到阈值

    async def test_none_outcome_counts_as_success(self) -> None:
        """返回 None（如简报委托）视为成功，不误报。"""
        calls: list[tuple[str, int, str]] = []
        runtime = self._runtime(calls)

        async def legacy() -> None:
            return None

        for _ in range(5):
            await runtime._guarded("job", legacy)
        assert calls == []

    async def test_exception_counts_failure_and_reraises(self) -> None:
        calls: list[tuple[str, int, str]] = []
        runtime = self._runtime(calls)

        async def exploding() -> None:
            raise RuntimeError("dispatch down")

        for _ in range(3):
            with self.assertRaises(RuntimeError):
                await runtime._guarded("daily_briefing", exploding)
        assert len(calls) == 1
        assert calls[0][2] == "dispatch down"


class AlertThresholdEnvTests(unittest.TestCase):
    def test_env_override_and_fallback(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"SCHEDULER_JOB_ALERT_FAILURE_THRESHOLD": "5"}):
            assert scheduler._alert_failure_threshold_from_env() == 5
        with patch.dict(os.environ, {"SCHEDULER_JOB_ALERT_FAILURE_THRESHOLD": "junk"}):
            assert scheduler._alert_failure_threshold_from_env() == 3
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCHEDULER_JOB_ALERT_FAILURE_THRESHOLD", None)
            assert scheduler._alert_failure_threshold_from_env() == 3


if __name__ == "__main__":
    unittest.main()
