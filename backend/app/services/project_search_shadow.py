from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import Counter, deque
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

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
        epoch_name: str = "default",
    ) -> None:
        if workers < 1 or capacity < workers:
            raise ValueError("search shadow capacity must be at least the worker count")
        if not 0 <= sample_rate <= 1 or timeout_seconds <= 0 or recent_case_limit < 0:
            raise ValueError("invalid project search shadow bounds")
        epoch_name = str(epoch_name).strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", epoch_name):
            raise ValueError("invalid project search shadow epoch name")
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="project-search-shadow")
        self._slots = threading.BoundedSemaphore(capacity)
        self._capacity = capacity
        self._sample_rate = sample_rate
        self._timeout_seconds = timeout_seconds
        self._epoch_name = epoch_name
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._finalized_at: str | None = None
        self._finalization_timed_out = False
        self._recent = deque(maxlen=recent_case_limit)
        self._counts: Counter[str] = Counter()
        self._accepted = 0
        self._futures: set[Future[Any]] = set()
        self._lock = threading.Lock()
        self._submission_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._executor_shutdown = False
        self._accepting = True

    def submit(
        self,
        *,
        arguments: Mapping[str, Any],
        legacy_repo_ids: Sequence[str],
        lanes: ProjectLexicalCandidateLanes | None = None,
        lanes_call: Callable[[], ProjectLexicalCandidateLanes] | None = None,
        semantic_repo_ids: Sequence[str],
        exact_repo_id: str = "",
    ) -> bool:
        fingerprint = _fingerprint(arguments)
        if not _should_sample(fingerprint, self._sample_rate):
            self._record("skipped_sampled")
            return False
        started = time.monotonic()
        with self._submission_lock:
            with self._lock:
                accepting = self._accepting
            if not accepting:
                self._record("skipped_unavailable")
                return False
            if not self._slots.acquire(blocking=False):
                self._record("skipped_saturated")
                return False
            try:
                future = self._executor.submit(
                    self._run,
                    fingerprint,
                    tuple(legacy_repo_ids),
                    lanes,
                    lanes_call,
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
                self._accepted += 1
            future.add_done_callback(self._done)
            return True

    def _run(
        self,
        fingerprint: str,
        legacy_repo_ids: tuple[str, ...],
        lanes: ProjectLexicalCandidateLanes | None,
        lanes_call: Callable[[], ProjectLexicalCandidateLanes] | None,
        semantic_repo_ids: tuple[str, ...],
        exact_repo_id: str,
        started: float,
    ) -> None:
        try:
            if lanes is None:
                if lanes_call is None:
                    raise ValueError("search shadow requires lanes or lanes_call")
                lanes = lanes_call()
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
            if not self._accepting and not self._futures and self._finalized_at is None:
                self._finalized_at = datetime.now(timezone.utc).isoformat()
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
            accepted = self._accepted
            sampled_out = self._counts.get("skipped_sampled", 0)
            skipped_unavailable = self._counts.get("skipped_unavailable", 0)
            skipped_saturated = self._counts.get("skipped_saturated", 0)
            submit_errors = self._counts.get("submit_error", 0)
            completed_terminal = sum(
                count
                for outcome, count in self._counts.items()
                if not outcome.startswith("skipped_") and outcome != "submit_error"
            )
            successful_terminal = self._counts.get("match", 0)
            terminal_failures = completed_terminal - successful_terminal
            in_flight = len(self._futures)
            eligible = accepted + skipped_unavailable + skipped_saturated + submit_errors
            attempted = sampled_out + eligible
            accounting_valid = (
                attempted == sampled_out + eligible
                and eligible == accepted + skipped_unavailable + skipped_saturated + submit_errors
                and accepted == completed_terminal + in_flight
            )
            complete_coverage = (
                self._sample_rate == 1
                and self._finalized_at is not None
                and not self._finalization_timed_out
                and sampled_out == 0
                and skipped_unavailable == 0
                and skipped_saturated == 0
                and submit_errors == 0
                and terminal_failures == 0
                and in_flight == 0
                and accounting_valid
            )
            return {
                "enabled": True,
                "epoch": self._epoch_name,
                "lifecycle": "finalized" if self._finalized_at else ("draining" if not self._accepting else "running"),
                "started_at": self._started_at,
                "finalized_at": self._finalized_at,
                "finalization_timed_out": self._finalization_timed_out,
                "capacity": self._capacity,
                "sample_rate": self._sample_rate,
                "in_flight": in_flight,
                "accounting": {
                    "attempted": attempted,
                    "eligible": eligible,
                    "sampled_out": sampled_out,
                    "accepted": accepted,
                    "completed_terminal": completed_terminal,
                    "successful_terminal": successful_terminal,
                    "terminal_failures": terminal_failures,
                    "in_flight": in_flight,
                    "skipped_unavailable": skipped_unavailable,
                    "skipped_saturated": skipped_saturated,
                    "submit_errors": submit_errors,
                    "accounting_valid": accounting_valid,
                    "complete_coverage": complete_coverage,
                    # Backward-compatible aggregate aliases.
                    "submitted": accepted,
                    "completed": completed_terminal,
                    "skipped": sampled_out + skipped_unavailable + skipped_saturated,
                },
                "counts": dict(self._counts),
                "recent_cases": list(self._recent),
            }

    def stop_accepting(self) -> None:
        with self._submission_lock:
            with self._lock:
                self._accepting = False
                futures = tuple(self._futures)
            for future in futures:
                future.cancel()

    def drain(self, timeout_seconds: float) -> bool:
        with self._lock:
            futures = tuple(self._futures)
        if futures:
            wait(futures, timeout=max(0.0, timeout_seconds))
        with self._lock:
            timed_out = bool(self._futures)
            self._finalization_timed_out = timed_out
            if not timed_out:
                self._finalized_at = datetime.now(timezone.utc).isoformat()
            return not timed_out

    def close(self, timeout_seconds: float) -> bool:
        with self._close_lock:
            self.stop_accepting()
            completed = self.drain(timeout_seconds)
            with self._lock:
                should_shutdown = not self._executor_shutdown
                self._executor_shutdown = True
            if should_shutdown:
                self._executor.shutdown(wait=True, cancel_futures=True)
            with self._lock:
                if not self._futures and self._finalized_at is None:
                    self._finalized_at = datetime.now(timezone.utc).isoformat()
            return completed


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
                epoch_name=str(getattr(config, "project_search_shadow_epoch", "default")),
            )
        return _manager


def finalize_project_search_shadow(timeout_seconds: float) -> dict[str, Any]:
    manager = _manager
    if manager is None:
        return project_search_shadow_snapshot()
    manager.close(timeout_seconds)
    return manager.snapshot()


def stop_project_search_shadow(timeout_seconds: float) -> None:
    global _manager
    with _manager_lock:
        manager, _manager = _manager, None
    if manager is not None:
        manager.close(timeout_seconds)


def project_search_shadow_snapshot() -> dict[str, Any]:
    manager = _manager
    if manager is None:
        return {
            "enabled": False,
            "epoch": None,
            "lifecycle": "disabled",
            "in_flight": 0,
            "accounting": {
                "attempted": 0,
                "submitted": 0,
                "completed": 0,
                "skipped": 0,
                "submit_errors": 0,
            },
            "counts": {},
            "recent_cases": [],
        }
    return manager.snapshot()
