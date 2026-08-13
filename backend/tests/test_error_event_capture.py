from __future__ import annotations

import contextlib
import io
import logging
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone

from backend.app.monitoring.error_event_capture import ErrorEventCapture


class FakeErrorEventRepository:
    def __init__(self, *, fail: bool = False) -> None:
        self.inserted = []
        self.pruned_cutoffs = []
        self.insert_calls = 0
        self.fail = fail

    def insert_events(self, events) -> int:
        self.insert_calls += 1
        if self.fail:
            raise RuntimeError("database is down")
        self.inserted.extend(events)
        return len(events)

    def prune_older_than(self, cutoff) -> int:
        self.pruned_cutoffs.append(cutoff)
        return 0


def _make_capture(repository: FakeErrorEventRepository | None = None, **overrides):
    repository = repository or FakeErrorEventRepository()
    options = {
        "flush_interval": 0.02,
        "batch_size": 10,
        "prune_interval": 3600.0,
        "backoff_base_seconds": 0.0001,
    }
    options.update(overrides)
    return ErrorEventCapture(repository, **options), repository


def _wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _installed_handlers():
    return [
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, "_aigc_error_event_handler", False)
    ]


class ErrorEventCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._captures: list[ErrorEventCapture] = []
        # pytest 收集阶段导入 main 会挂出应用级采集 handler（模块级
        # install_handler）。每个用例开始前先清掉，保证 install_handler
        # 幂等判定从干净状态起步。
        root = logging.getLogger()
        for handler in _installed_handlers():
            root.removeHandler(handler)

    def tearDown(self) -> None:
        for capture in self._captures:
            capture.stop()
        root = logging.getLogger()
        for handler in _installed_handlers():
            root.removeHandler(handler)
        # 恢复应用级采集 handler（若 main 已被其他测试模块导入），
        # 让后续模块看到与收集阶段一致的全局 logging 状态。
        main_module = sys.modules.get("backend.app.main")
        if main_module is not None:
            main_module.error_event_capture.install_handler()

    def _capture(self, repository=None, **overrides) -> tuple:
        capture, repository = _make_capture(repository, **overrides)
        self._captures.append(capture)
        return capture, repository

    def test_logged_exception_is_persisted_with_field_mapping(self) -> None:
        capture, repository = self._capture()
        capture.install_handler()
        capture.start()

        try:
            raise ValueError("ingestion blew up")
        except ValueError:
            logging.getLogger("test.capture").exception("[Scheduler] job failed")

        assert _wait_for(lambda: len(repository.inserted) == 1)
        capture.stop()

        event = repository.inserted[0]
        assert event.level == "ERROR"
        assert event.logger_name == "test.capture"
        assert event.message == "[Scheduler] job failed"
        assert event.exception_type == "ValueError"
        assert "ingestion blew up" in event.stack_trace
        assert "Traceback" in event.stack_trace
        # occurred_at 由采集层从 record.created 转换为 UTC  aware datetime
        assert isinstance(event.occurred_at, datetime)
        assert event.occurred_at.tzinfo is not None

    def test_plain_error_without_exc_info_has_nullable_fields(self) -> None:
        capture, repository = self._capture()
        capture.install_handler()
        capture.start()

        logging.getLogger("test.capture").error("simple failure")

        assert _wait_for(lambda: len(repository.inserted) == 1)
        capture.stop()

        event = repository.inserted[0]
        assert event.exception_type is None
        assert event.stack_trace is None

    def test_handler_ignores_records_below_error_level(self) -> None:
        capture, repository = self._capture()
        capture.install_handler()
        capture.start()

        logging.getLogger("test.capture").warning("not an error")

        capture.stop()
        assert repository.insert_calls == 0

    def test_queue_full_drops_newest_without_raising(self) -> None:
        capture, repository = self._capture(max_queue=1)
        capture.install_handler()
        # 不启动 listener：队列必然填满

        logging.getLogger("test.capture").error("first")
        logging.getLogger("test.capture").error("second")

        assert capture.dropped_count == 1
        capture.start()
        assert _wait_for(lambda: len(repository.inserted) == 1)
        capture.stop()
        assert repository.inserted[0].message == "first"

    def test_flush_failure_goes_to_stderr_and_thread_survives(self) -> None:
        repository = FakeErrorEventRepository(fail=True)
        capture, _ = self._capture(repository)
        capture.install_handler()
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            capture.start()
            logging.getLogger("test.capture").error("will fail to flush")
            assert _wait_for(lambda: repository.insert_calls >= 1)
            # 连续失败计数 + 退避后线程仍存活，且错误只进 stderr
            assert _wait_for(lambda: capture._consecutive_flush_failures >= 1)
            capture.stop()

        assert "flush failed" in stderr.getvalue()
        assert repository.inserted == []

    def test_stop_flushes_pending_batch(self) -> None:
        capture, repository = self._capture(flush_interval=60.0)
        capture.install_handler()
        capture.start()

        logging.getLogger("test.capture").error("pending at shutdown")
        # flush_interval 很大：只有 stop() 的收尾 drain 会写出这批
        capture.stop()

        assert [event.message for event in repository.inserted] == ["pending at shutdown"]

    def test_install_handler_is_idempotent(self) -> None:
        capture, _ = self._capture()

        capture.install_handler()
        capture.install_handler()

        assert len(_installed_handlers()) == 1

    def test_prune_once_delegates_with_retention_cutoff(self) -> None:
        capture, repository = self._capture(retention_days=30)

        assert capture.prune_once() == 0

        assert len(repository.pruned_cutoffs) == 1
        cutoff = repository.pruned_cutoffs[0]
        expected = datetime.now(timezone.utc) - timedelta(days=30)
        assert abs((cutoff - expected).total_seconds()) < 60

    def test_lazy_repository_binding(self) -> None:
        # 单一实例走完整生产生命周期：模块级 install_handler（未绑定）→
        # lifespan 内 bind_repository → start。handler 幂等标记保证 root 上
        # 始终只有这一个实例的 handler，绑定前后路由一致。
        repository = FakeErrorEventRepository()
        capture = ErrorEventCapture(flush_interval=0.02, backoff_base_seconds=0.0001)
        self._captures.append(capture)

        # 未绑定：清理 no-op，flush 丢批仅 stderr 报告，线程不炸
        assert capture.prune_once() == 0
        capture.install_handler()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            capture.start()
            logging.getLogger("test.capture").error("dropped while unbound")
            assert _wait_for(lambda: "repository not bound" in stderr.getvalue())
            capture.stop()
        assert repository.inserted == []

        # 绑定后正常写入（install_handler 幂等，不再重复挂载）
        capture.bind_repository(repository)
        capture.install_handler()
        capture.start()
        logging.getLogger("test.capture").error("written after bind")
        assert _wait_for(lambda: len(repository.inserted) == 1)
        capture.stop()
        assert repository.inserted[0].message == "written after bind"


if __name__ == "__main__":
    unittest.main()
