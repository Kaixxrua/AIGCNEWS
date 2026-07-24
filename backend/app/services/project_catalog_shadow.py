from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import Counter, deque
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from backend.app.repositories.project_catalog import ProjectCatalogRepository

logger = logging.getLogger(__name__)

_PUBLIC_PROJECT_FIELDS = (
    "id",
    "repo_id",
    "source",
    "full_name",
    "url",
    "category_slug",
    "subcategory_slug",
    "tags",
    "topics",
    "language",
    "stars",
    "forks",
    "pushed_at",
    "daily_star_growth",
    "daily_growth_available",
    "hot_score",
    "is_recommended",
    "is_favorite",
    "is_user_added",
    "availability_status",
)
_SENSITIVE_ARGUMENTS = {"q", "user_id", "candidate_repo_ids", "tag", "category", "subcategory", "language"}


def _canonical_bytes(value: Any) -> bytes:
    def normalize(item: Any) -> Any:
        if item is None or isinstance(item, (bool, int, float, str)):
            return item
        if isinstance(item, Mapping):
            return [[str(key), normalize(item[key])] for key in sorted(item, key=str)]
        if isinstance(item, (list, tuple)):
            return [normalize(entry) for entry in item]
        return str(item)

    return json.dumps(normalize(value), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def argument_fingerprint(method: str, arguments: Mapping[str, Any]) -> str:
    values = {}
    for key, value in arguments.items():
        values[key] = _digest(value) if key in _SENSITIVE_ARGUMENTS else value
    return _digest({"method": method, "arguments": values})


def should_sample(fingerprint: str, rate: float) -> bool:
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    threshold = int(rate * (1 << 64))
    return int(fingerprint[:16], 16) < threshold


def _project_identity(item: Mapping[str, Any]) -> str:
    return str(item.get("repo_id") or item.get("id") or "")


def _compare_sequences(primary: list[Any], shadow: list[Any]) -> str:
    if len(primary) != len(shadow):
        return "count_mismatch"
    if _digest(sorted(primary, key=_canonical_bytes)) != _digest(
        sorted(shadow, key=_canonical_bytes)
    ):
        return "set_mismatch"
    if _digest(primary) != _digest(shadow):
        return "order_mismatch"
    return "match"


def compare_results(method: str, primary: Any, shadow: Any) -> tuple[str, str, str]:
    if method == "find_lexical_candidate_repo_ids":
        primary_ids = [str(value) for value in primary]
        shadow_ids = [str(value) for value in shadow]
        outcome = _compare_sequences(primary_ids, shadow_ids)
        if outcome == "match" and (
            len(primary_ids) != len(set(primary_ids))
            or len(shadow_ids) != len(set(shadow_ids))
        ):
            outcome = "duplicate_mismatch"
        return outcome, _digest(primary_ids), _digest(shadow_ids)

    if method == "list_projects":
        primary_envelope = {key: primary.get(key) for key in ("total", "page", "page_size")}
        shadow_envelope = {key: shadow.get(key) for key in ("total", "page", "page_size")}
        if primary_envelope != shadow_envelope:
            outcome = "pagination_mismatch"
        else:
            primary_items = list(primary.get("items") or [])
            shadow_items = list(shadow.get("items") or [])
            outcome = _compare_sequences(
                [_project_identity(item) for item in primary_items],
                [_project_identity(item) for item in shadow_items],
            )
            if outcome == "match":
                primary_fields = [
                    {key: item.get(key) for key in _PUBLIC_PROJECT_FIELDS}
                    for item in primary_items
                ]
                shadow_fields = [
                    {key: item.get(key) for key in _PUBLIC_PROJECT_FIELDS}
                    for item in shadow_items
                ]
                if _digest(primary_fields) != _digest(shadow_fields):
                    outcome = "field_mismatch"
        return outcome, _digest(primary), _digest(shadow)

    if method == "get_project_categories":
        envelope_keys = ("total", "today_count", "recommended_count")
        if any(primary.get(key) != shadow.get(key) for key in envelope_keys):
            outcome = "count_mismatch"
        else:
            outcome = _compare_sequences(
                list(primary.get("items") or []),
                list(shadow.get("items") or []),
            )
            if outcome == "set_mismatch":
                outcome = "category_mismatch"
        return outcome, _digest(primary), _digest(shadow)

    raise ValueError("unsupported project catalog shadow method")


class ProjectCatalogShadowManager:
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
            raise ValueError("shadow capacity must be at least the worker count")
        if not 0 <= sample_rate <= 1:
            raise ValueError("shadow sample rate must be between zero and one")
        if timeout_seconds <= 0 or recent_case_limit < 0:
            raise ValueError("invalid project catalog shadow bounds")
        self._executor = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="project-catalog-shadow",
        )
        self._capacity = capacity
        self._sample_rate = sample_rate
        self._timeout_seconds = timeout_seconds
        self._recent = deque(maxlen=recent_case_limit)
        self._slots = threading.BoundedSemaphore(capacity)
        self._lock = threading.Lock()
        self._futures: set[Future[Any]] = set()
        self._counts: Counter[tuple[str, str]] = Counter()
        self._latencies: list[float] = []
        self._accepting = True
        self._available = True
        self._error_class: str | None = None
        self._last_success_at: str | None = None
        self._last_mismatch_at: str | None = None

    def submit(
        self,
        *,
        method: str,
        arguments: Mapping[str, Any],
        primary: Any,
        shadow_call: Callable[[], Any],
    ) -> bool:
        fingerprint = argument_fingerprint(method, arguments)
        if not should_sample(fingerprint, self._sample_rate):
            self._record(method, "skipped_sampled")
            return False
        with self._lock:
            accepting = self._accepting and self._available
        if not accepting:
            self._record(method, "skipped_unavailable")
            return False
        if not self._slots.acquire(blocking=False):
            self._record(method, "skipped_saturated")
            return False
        started = time.monotonic()
        try:
            future = self._executor.submit(
                self._run,
                method,
                fingerprint,
                primary,
                shadow_call,
                started,
            )
        except BaseException:
            self._slots.release()
            self._record(method, "submit_error")
            return False
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._done)
        return True

    def _run(
        self,
        method: str,
        fingerprint: str,
        primary: Any,
        shadow_call: Callable[[], Any],
        started: float,
    ) -> None:
        try:
            shadow = shadow_call()
            elapsed = time.monotonic() - started
            outcome, primary_digest, shadow_digest = compare_results(
                method, primary, shadow
            )
            if elapsed > self._timeout_seconds:
                outcome = "shadow_timeout"
            self._record_case(
                method,
                outcome,
                fingerprint,
                primary_digest,
                shadow_digest,
                elapsed,
            )
        except Exception as exc:
            elapsed = time.monotonic() - started
            outcome = "shadow_timeout" if elapsed > self._timeout_seconds else "shadow_error"
            self._record_case(
                method,
                outcome,
                fingerprint,
                "",
                "",
                elapsed,
                error_class=type(exc).__name__,
            )

    def _done(self, future: Future[Any]) -> None:
        with self._lock:
            self._futures.discard(future)
        self._slots.release()

    def _record(self, method: str, outcome: str) -> None:
        with self._lock:
            self._counts[(method, outcome)] += 1

    def _record_case(
        self,
        method: str,
        outcome: str,
        fingerprint: str,
        primary_digest: str,
        shadow_digest: str,
        elapsed: float,
        *,
        error_class: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._counts[(method, outcome)] += 1
            self._latencies.append(elapsed * 1000)
            if len(self._latencies) > 1000:
                del self._latencies[: len(self._latencies) - 1000]
            if outcome == "match":
                self._last_success_at = now
            else:
                self._last_mismatch_at = now
            self._recent.append(
                {
                    "method": method,
                    "outcome": outcome,
                    "argument_sha256": fingerprint,
                    "primary_sha256": primary_digest,
                    "shadow_sha256": shadow_digest,
                    "latency_ms": round(elapsed * 1000, 3),
                    "error_class": error_class,
                    "observed_at": now,
                }
            )
        if outcome != "match":
            logger.warning(
                "project_catalog_shadow method=%s outcome=%s case=%s latency_ms=%.3f error_class=%s",
                method,
                outcome,
                fingerprint,
                elapsed * 1000,
                error_class or "",
            )

    def mark_unavailable(self, exc: Exception) -> None:
        with self._lock:
            self._available = False
            self._error_class = type(exc).__name__

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counts: dict[str, dict[str, int]] = {}
            for (method, outcome), count in self._counts.items():
                counts.setdefault(method, {})[outcome] = count
            latencies = sorted(self._latencies)
            p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None
            return {
                "enabled": True,
                "available": self._available,
                "degraded": not self._available,
                "active_backend": "mysql",
                "shadow_backend": "postgres",
                "capacity": self._capacity,
                "in_flight": len(self._futures),
                "counts": counts,
                "latency_p95_ms": p95,
                "last_success_at": self._last_success_at,
                "last_mismatch_at": self._last_mismatch_at,
                "error_class": self._error_class,
                "recent_cases": list(self._recent),
            }

    def close(self, timeout_seconds: float) -> None:
        with self._lock:
            self._accepting = False
            futures = tuple(self._futures)
        if futures:
            wait(futures, timeout=max(0.0, timeout_seconds))
        # Running database calls cannot be force-cancelled safely.  Wait for the
        # database-side statement timeout before returning the pool to shutdown.
        self._executor.shutdown(wait=True, cancel_futures=True)


class ShadowComparingProjectCatalogRepository:
    def __init__(
        self,
        active: ProjectCatalogRepository,
        shadow: ProjectCatalogRepository,
        manager: ProjectCatalogShadowManager,
    ) -> None:
        self._active = active
        self._shadow = shadow
        self._manager = manager

    def _call(self, method: str, arguments: dict[str, Any]) -> Any:
        result = getattr(self._active, method)(**arguments)
        self._manager.submit(
            method=method,
            arguments=arguments,
            primary=json.loads(json.dumps(result, default=str)),
            shadow_call=lambda: getattr(self._shadow, method)(**arguments),
        )
        return result

    def find_lexical_candidate_repo_ids(self, **kwargs: Any) -> list[str]:
        return self._call("find_lexical_candidate_repo_ids", kwargs)

    def list_projects(self, **kwargs: Any) -> dict[str, Any]:
        return self._call("list_projects", kwargs)

    def get_project_categories(self, **kwargs: Any) -> dict[str, Any]:
        return self._call("get_project_categories", kwargs)


_manager: ProjectCatalogShadowManager | None = None
_manager_lock = threading.Lock()


def start_project_catalog_shadow(config: Any) -> ProjectCatalogShadowManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = ProjectCatalogShadowManager(
                workers=int(config.project_catalog_shadow_workers),
                capacity=int(config.project_catalog_shadow_capacity),
                sample_rate=float(config.project_catalog_shadow_sample_rate),
                timeout_seconds=float(config.project_catalog_shadow_timeout_seconds),
                recent_case_limit=int(config.project_catalog_shadow_recent_case_limit),
            )
        return _manager


def get_project_catalog_shadow_manager() -> ProjectCatalogShadowManager | None:
    return _manager


def stop_project_catalog_shadow(timeout_seconds: float) -> None:
    global _manager
    with _manager_lock:
        manager, _manager = _manager, None
    if manager is not None:
        manager.close(timeout_seconds)


def project_catalog_shadow_snapshot() -> dict[str, Any]:
    manager = get_project_catalog_shadow_manager()
    if manager is None:
        return {
            "enabled": False,
            "available": False,
            "degraded": False,
            "active_backend": "mysql",
            "shadow_backend": "postgres",
            "counts": {},
            "recent_cases": [],
        }
    return manager.snapshot()
