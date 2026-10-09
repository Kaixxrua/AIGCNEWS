"""Scheduler alert policy, isolated from job registration and runtime ownership."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

_DEFAULT_ALERT_FAILURE_THRESHOLD = 3

_ALERT_FAILURE_THRESHOLD_ENV = "SCHEDULER_JOB_ALERT_FAILURE_THRESHOLD"

_OPS_ALERT_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "notify_ops_alert.py"

_DEFAULT_ZERO_INGEST_ALERT_THRESHOLD = 3

_ZERO_INGEST_THRESHOLD_ENV = "SCHEDULER_ZERO_INGEST_ALERT_THRESHOLD"

_ZERO_INGEST_SOURCES_ENV = "SCHEDULER_ZERO_INGEST_WATCH_SOURCES"

_DEFAULT_ZERO_INGEST_WATCH_SOURCES = (
    "arxiv",
    "github",
    "news",
    "producthunt",
    "hackernews",
)


def _notify_ops_alert(job_id: str, failures: int, detail: str) -> None:
    """经 scripts/notify_ops_alert.py 发送调度器失败告警（fire-and-forget）。

    SMTP 发送放到 daemon 线程，避免阻塞事件循环；脚本缺失或发送失败只记日志，
    告警链路绝不能反过来影响调度任务本身。
    """
    if not _OPS_ALERT_SCRIPT.is_file():
        logger.warning("[Scheduler] 告警脚本不存在，跳过告警: %s", _OPS_ALERT_SCRIPT)
        return

    def _send() -> None:
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(_OPS_ALERT_SCRIPT),
                    "--failed-unit",
                    f"scheduler-job:{job_id}",
                    "--detail",
                    f"连续失败 {failures} 次。{detail}"[:400],
                    "--no-journal",
                ],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if result.returncode != 0:
                logger.warning(
                    "[Scheduler] 告警脚本退出码 %d: %s",
                    result.returncode,
                    (result.stderr or "").strip()[:200],
                )
        except Exception as exc:
            logger.warning("[Scheduler] 发送调度器告警失败（非致命）: %s", exc)

    threading.Thread(target=_send, name=f"ops-alert-{job_id}", daemon=True).start()


class _ConsecutiveFailureAlerter:
    """按 job 统计连续失败次数的去抖告警器。

    仅当连续失败计数「到达」阈值时告警一次（不为每次失败都发邮件）；
    一次成功后计数重置，再次连续失败到阈值会重新告警。
    """

    def __init__(
        self,
        *,
        threshold: int = _DEFAULT_ALERT_FAILURE_THRESHOLD,
        notifier: Callable[[str, int, str], None] | None = None,
    ) -> None:
        self._threshold = max(1, int(threshold))
        self._notifier = notifier or _notify_ops_alert
        self._consecutive_failures: Dict[str, int] = {}

    def record_success(self, job_id: str) -> None:
        self._consecutive_failures.pop(job_id, None)

    def record_failure(self, job_id: str, detail: str = "") -> None:
        count = self._consecutive_failures.get(job_id, 0) + 1
        self._consecutive_failures[job_id] = count
        if count == self._threshold:
            logger.error(
                "[Scheduler] 任务 %s 已连续失败 %d 次，触发运维告警。",
                job_id,
                count,
            )
            try:
                self._notifier(job_id, count, detail)
            except Exception as exc:
                logger.warning("[Scheduler] 触发运维告警失败（非致命）: %s", exc)
        elif count > self._threshold:
            logger.warning(
                "[Scheduler] 任务 %s 已连续失败 %d 次（告警已发，不再重复）。",
                job_id,
                count,
            )


def _alert_failure_threshold_from_env() -> int:
    raw = os.environ.get(_ALERT_FAILURE_THRESHOLD_ENV, "").strip()
    if not raw:
        return _DEFAULT_ALERT_FAILURE_THRESHOLD
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning(
            "[Scheduler] %s=%r 不是整数，使用默认告警阈值 %d。",
            _ALERT_FAILURE_THRESHOLD_ENV,
            raw,
            _DEFAULT_ALERT_FAILURE_THRESHOLD,
        )
        return _DEFAULT_ALERT_FAILURE_THRESHOLD


class _ZeroIngestAlerter:
    """按源统计连续零入库轮次的去抖告警器。

    与 _ConsecutiveFailureAlerter 同一去抖口径：仅当连续零入库「到达」
    阈值时告警一次；某轮入库 > 0 即重置，之后再次连续零入库到阈值会重新
    告警。不在盯防集合内的源直接忽略。
    """

    def __init__(
        self,
        *,
        threshold: int = _DEFAULT_ZERO_INGEST_ALERT_THRESHOLD,
        watch_sources: tuple[str, ...] = _DEFAULT_ZERO_INGEST_WATCH_SOURCES,
        notifier: Callable[[str, int, str], None] | None = None,
    ) -> None:
        self._threshold = max(1, int(threshold))
        self._watch_sources = frozenset(watch_sources)
        self._notifier = notifier or _notify_ops_alert
        self._consecutive_zeros: Dict[str, int] = {}

    def record(self, source: str, ingested: int) -> None:
        if source not in self._watch_sources:
            return
        if ingested > 0:
            self._consecutive_zeros.pop(source, None)
            return
        count = self._consecutive_zeros.get(source, 0) + 1
        self._consecutive_zeros[source] = count
        if count == self._threshold:
            logger.error(
                "[Scheduler] 数据源 %s 已连续 %d 轮零入库，触发运维告警。",
                source,
                count,
            )
            try:
                self._notifier(
                    f"zero-ingest:{source}",
                    count,
                    f"数据源 {source} 连续 {count} 轮采集成功但零入库，疑似网络/代理或上游断供。",
                )
            except Exception as exc:
                logger.warning("[Scheduler] 触发零入库告警失败（非致命）: %s", exc)
        elif count > self._threshold:
            logger.warning(
                "[Scheduler] 数据源 %s 已连续 %d 轮零入库（告警已发，不再重复）。",
                source,
                count,
            )


def _zero_ingest_threshold_from_env() -> int:
    raw = os.environ.get(_ZERO_INGEST_THRESHOLD_ENV, "").strip()
    if not raw:
        return _DEFAULT_ZERO_INGEST_ALERT_THRESHOLD
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning(
            "[Scheduler] %s=%r 不是整数，使用默认零入库告警阈值 %d。",
            _ZERO_INGEST_THRESHOLD_ENV,
            raw,
            _DEFAULT_ZERO_INGEST_ALERT_THRESHOLD,
        )
        return _DEFAULT_ZERO_INGEST_ALERT_THRESHOLD


def _zero_ingest_watch_sources_from_env() -> tuple[str, ...]:
    raw = os.environ.get(_ZERO_INGEST_SOURCES_ENV, "").strip()
    if not raw:
        return _DEFAULT_ZERO_INGEST_WATCH_SOURCES
    sources = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not sources:
        logger.warning(
            "[Scheduler] %s=%r 解析为空，使用默认零入库盯防源。",
            _ZERO_INGEST_SOURCES_ENV,
            raw,
        )
        return _DEFAULT_ZERO_INGEST_WATCH_SOURCES
    return sources
