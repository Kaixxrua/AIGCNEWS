from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import Counter, deque
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from backend.app.repositories.project_catalog import ProjectLexicalCandidateLanes
from backend.app.services.project_search_ranking import rank_v2_project_candidate_ids


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fingerprint(arguments: Mapping[str, Any]) -> str:
    sanitized = {
        key: _digest(value) if key in {"query", "category", "subcategory", "language"} else value
        for key, value in arguments.items()
    }
    return _digest(sanitized)


def _should_sample(fingerprint: str, rate: float) -> bool:
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    return int(fingerprint[:16], 16) < int(rate * (1 << 64))


class ProjectSearchShadowManager:
    def __init__(
        self,
        *,
        workers: int,
        capacity: int,
        sample_rate: float,
        timeout_seconds: float,
        recent_case_limit: int,
    ) -> None:
        if workers < 1 or capacity < workers:
            raise ValueError("search shadow capacity must be at least the worker count")
        if not 0 <= sample_rate <= 1 or timeout_seconds <= 0 or recent_case_limit < 0:
            raise ValueError("invalid project search shadow bounds")
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="project-search-shadow")
        self._slots = threading.BoundedSemaphore(capacity)
        self._sample_rate = sample_rate
        self._timeout_seconds = timeout_seconds
        self._recent = deque(maxlen=recent_case_limit)
        self._counts: Counter[str] = Counter()
        self._futures: set[Future[Any]] = set()
        self._lock = threading.Lock()

    def submit(
        self,
        *,
        arguments: Mapping[str, Any],
        legacy_repo_ids: Sequence[str],
        lanes: ProjectLexicalCandidateLanes,
        semantic_repo_ids: Sequence[str],
        exact_repo_id: str = "",
    ) -> bool:
        fingerprint = _fingerprint(arguments)
        if not _should_sample(fingerprint, self._sample_rate):
            self._record("skipped_sampled")
            return False
        if not self._slots.acquire(blocking=False):
            self._record("skipped_saturated")
            return False
        started = time.monotonic()
        try:
            future = self._executor.submit(
                self._run,
                fingerprint,
                tuple(legacy_repo_ids),
                lanes,
                tuple(semantic_repo_ids),
                exact_repo_id,
                started,
            )
        except BaseException:
            self._slots.release()
            self._record("submit_error")
            return False
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._done)
        return True

    def _run(
        self,
        fingerprint: str,
        legacy_repo_ids: tuple[str, ...],
        lanes: ProjectLexicalCandidateLanes,
        semantic_repo_ids: tuple[str, ...],
        exact_repo_id: str,
        started: float,
    ) -> None:
        try:
            v2_repo_ids = rank_v2_project_candidate_ids(
                lanes.strict,
                lanes.relaxed,
                semantic_repo_ids,
                exact_repo_id=exact_repo_id,
            )
            elapsed = time.monotonic() - started
            outcome = "shadow_timeout" if elapsed > self._timeout_seconds else (
                "match" if list(legacy_repo_ids) == v2_repo_ids else "order_mismatch"
            )
            self._record_case(
                outcome,
                fingerprint,
                elapsed,
                strict_count=len(lanes.strict),
                relaxed_count=len(lanes.relaxed),
                semantic_count=len(semantic_repo_ids),
                fused_count=len(v2_repo_ids),
            )
        except Exception as exc:
            elapsed = time.monotonic() - started
            self._record_case(
                "shadow_timeout" if elapsed > self._timeout_seconds else "shadow_error",
                fingerprint,
                elapsed,
                error_class=type(exc).__name__,
            )

    def _done(self, future: Future[Any]) -> None:
        with self._lock:
            self._futures.discard(future)
        self._slots.release()

    def _record(self, outcome: str) -> None:
        with self._lock:
            self._counts[outcome] += 1

    def _record_case(
        self,
        outcome: str,
        fingerprint: str,
        elapsed: float,
        *,
        strict_count: int = 0,
        relaxed_count: int = 0,
        semantic_count: int = 0,
        fused_count: int = 0,
        error_class: str | None = None,
    ) -> None:
        with self._lock:
            self._counts[outcome] += 1
            self._recent.append(
                {
                    "outcome": outcome,
                    "argument_sha256": fingerprint,
                    "latency_ms": round(elapsed * 1000, 3),
                    "strict_count": strict_count,
                    "relaxed_count": relaxed_count,
                    "semantic_count": semantic_count,
                    "fused_count": fused_count,
                    "error_class": error_class,
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                }
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": True,
                "in_flight": len(self._futures),
                "counts": dict(self._counts),
                "recent_cases": list(self._recent),
            }


_manager: ProjectSearchShadowManager | None = None
_manager_lock = threading.Lock()


def get_project_search_shadow_manager(config: Any) -> ProjectSearchShadowManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = ProjectSearchShadowManager(
                workers=int(getattr(config, "project_search_shadow_workers", 2)),
                capacity=int(getattr(config, "project_search_shadow_capacity", 8)),
                sample_rate=float(getattr(config, "project_search_shadow_sample_rate", 0.0)),
                timeout_seconds=float(getattr(config, "project_search_shadow_timeout_seconds", 1.0)),
                recent_case_limit=int(getattr(config, "project_search_shadow_recent_case_limit", 20)),
            )
        return _manager


def project_search_shadow_snapshot() -> dict[str, Any]:
    manager = _manager
    if manager is None:
        return {"enabled": False, "in_flight": 0, "counts": {}, "recent_cases": []}
    return manager.snapshot()
