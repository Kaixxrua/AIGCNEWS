"""后端错误事件采集：root logger 上的 ERROR 级队列式 Handler。

设计要点：
- 现有全部 ``logger.error``/``logger.exception`` 调用点零改动自动汇入
  ``error_events`` 表（调度器、采集管线、服务层、启动守卫）。
- Handler 只做 record → dict 转换和 ``put_nowait``，绝不阻塞事件循环；
  独立的 daemon 线程批量 flush 到 PostgreSQL（psycopg 为同步驱动）。
- 递归防护：flush/清理失败只写 ``sys.stderr``，永不调用 logger——
  否则 DB 宕机会形成"写错误日志失败 → 再产生错误日志"的自激环路。
- 队列有界，满了 drop-newest 并计数；flush 连续失败指数退避封顶 60s，
  避免迁移滞后（0037 未应用）或 DB 宕机时 stderr 风暴。
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.repositories.error_event_repository import (
    ErrorEventInsert,
    ErrorEventWriter,
)

_MESSAGE_MAX_CHARS = 8000
_STACK_TRACE_MAX_CHARS = 16000
_LOGGER_NAME_MAX_CHARS = 255

_STOP_SENTINEL: Any = object()


def _format_exc_info(exc_info: Any) -> str:
    try:
        return "".join(traceback.format_exception(*exc_info))
    except Exception:
        # exc_info 畸形时退化为 repr，采集路径绝不外抛
        return repr(exc_info)


class _ErrorEventQueueHandler(logging.Handler):
    """把 ERROR+ record 转成普通 dict 投进有界队列；任何失败静默。"""

    _aigc_error_event_handler = True

    def __init__(self, event_queue: queue.Queue, capture: ErrorEventCapture) -> None:
        super().__init__(level=logging.ERROR)
        self._event_queue = event_queue
        self._capture = capture

    def emit(self, record: logging.LogRecord) -> None:
        try:
            exc_info = record.exc_info
            payload = {
                "occurred_at": datetime.fromtimestamp(record.created, tz=timezone.utc),
                "level": record.levelname,
                "logger_name": record.name[:_LOGGER_NAME_MAX_CHARS],
                "message": record.getMessage()[:_MESSAGE_MAX_CHARS],
                "exception_type": (
                    type(exc_info[1]).__name__ if exc_info and exc_info[1] else None
                ),
                "stack_trace": (
                    _format_exc_info(exc_info)[:_STACK_TRACE_MAX_CHARS]
                    if exc_info and exc_info[1]
                    else None
                ),
            }
            self._event_queue.put_nowait(payload)
        except queue.Full:
            self._capture._dropped_count += 1
        except Exception:
            # logging 路径绝不外抛（logging.raiseExceptions 下 handleError
            # 也只是 stderr 打印，这里连打印都省掉，保持采集零副作用）
            pass


class ErrorEventCapture:
    """队列式错误事件采集器：install_handler → start → stop 三段生命周期。"""

    def __init__(
        self,
        repository: ErrorEventWriter | None = None,
        *,
        max_queue: int = 2000,
        batch_size: int = 50,
        flush_interval: float = 1.0,
        prune_interval: float = 3600.0,
        retention_days: int = 30,
        backoff_base_seconds: float = 2.0,
    ) -> None:
        self._repository = repository
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._prune_interval = prune_interval
        self._retention_days = retention_days
        self._backoff_base_seconds = backoff_base_seconds
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue)
        self._thread: threading.Thread | None = None
        self._dropped_count = 0
        self._consecutive_flush_failures = 0
        self._last_prune_monotonic = 0.0

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    def install_handler(self) -> None:
        """挂到 root logger；幂等（交替模块名双导入/reload 兜底）。"""
        root = logging.getLogger()
        for handler in root.handlers:
            if getattr(handler, "_aigc_error_event_handler", False):
                return
        root.addHandler(_ErrorEventQueueHandler(self._queue, self))

    def bind_repository(self, repository: ErrorEventWriter) -> None:
        """lifespan 内绑定当前应用数据库对应的仓储。

        延迟绑定的意义：模块级 install_handler 只收集 record 不触库；
        仓储在 lifespan 里按当时的 postgres_database 全局构造——单测整体
        替换该全局（MagicMock）时，采集也随之落到 mock，不会对真实
        连接单例发起连接尝试。
        """
        self._repository = repository

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        # 周期清理从 start 起算（启动即时清理由 lifespan 显式调 prune_once）
        self._last_prune_monotonic = time.monotonic()
        self._thread = threading.Thread(
            target=self._run,
            name="error-event-capture",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._queue.put(_STOP_SENTINEL)
        thread.join(timeout=5.0)
        self._thread = None

    def prune_once(self) -> int:
        if self._repository is None:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        return self._repository.prune_older_than(cutoff)

    # ── 后台线程内部 ─────────────────────────────────────────────────────────

    def _run(self) -> None:
        while True:
            batch = self._next_batch()
            if batch and batch[-1] is _STOP_SENTINEL:
                batch = batch[:-1]
                if batch:
                    self._flush(batch)
                return
            if batch:
                self._flush(batch)
            self._maybe_prune()

    def _next_batch(self) -> list[Any]:
        try:
            first = self._queue.get(timeout=self._flush_interval)
        except queue.Empty:
            return []
        batch = [first]
        while len(batch) < self._batch_size:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is _STOP_SENTINEL:
                batch.append(item)
                break
            batch.append(item)
        return batch

    def _flush(self, batch: list[dict[str, Any]]) -> None:
        if self._repository is None:
            # start() 前不应发生；防御性丢批防线程崩溃
            self._report_internal_failure("flush (repository not bound)")
            return
        try:
            events = [ErrorEventInsert(**payload) for payload in batch]
            self._repository.insert_events(events)
        except BaseException:
            # 递归防护：只写 stderr，永不 logger；退避封顶 60s
            self._consecutive_flush_failures += 1
            self._report_internal_failure("flush")
            time.sleep(
                min(60.0, self._backoff_base_seconds**self._consecutive_flush_failures)
            )
            return
        self._consecutive_flush_failures = 0

    def _maybe_prune(self) -> None:
        now = time.monotonic()
        if now - self._last_prune_monotonic < self._prune_interval:
            return
        self._last_prune_monotonic = now
        try:
            self.prune_once()
        except BaseException:
            self._report_internal_failure("prune")

    @staticmethod
    def _report_internal_failure(operation: str) -> None:
        try:
            sys.stderr.write(
                f"[ErrorEventCapture] {operation} failed:\n{traceback.format_exc()}"
            )
        except Exception:
            pass
