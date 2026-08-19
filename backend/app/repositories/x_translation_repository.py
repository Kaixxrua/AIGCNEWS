from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol, TypedDict

XTranslationTargetKind = Literal["outer", "quote"]
XTranslationTaskStatus = Literal[
    "pending", "running", "succeeded", "failed", "skipped"
]


class XTranslationStatusSummary(TypedDict):
    pending: int
    running: int
    succeeded: int
    failed: int
    skipped: int
    retryable: int
    stale_running: int
    oldest_pending_at: datetime | None
    latest_failure_at: datetime | None
    latest_failure_error: str | None
    latest_failure_model_provider: str | None
    latest_failure_model_name: str | None
    latest_failure_prompt_version: str | None


class XTranslationTaskRepository(Protocol):
    """Persistence boundary for durable X translation work."""

    def count_retryable(self, stale_after_seconds: int = 900) -> int: ...

    def get_status_summary(
        self, stale_after_seconds: int = 900
    ) -> XTranslationStatusSummary: ...

    def recover_stale_running(self, stale_after_seconds: int = 900) -> int: ...

    def claim_retryable(
        self, limit: int, lease_seconds: int = 900
    ) -> list[dict[str, Any]]: ...

    def increment_attempt(self, task_id: int, claim_token: str) -> bool: ...

    def complete_task(
        self,
        task_id: int,
        translation_zh: str,
        model_provider: str,
        model_name: str,
        claim_token: str = "",
    ) -> bool: ...

    def fail_task(
        self,
        task_id: int,
        error: str,
        model_provider: str,
        model_name: str,
        claim_token: str = "",
    ) -> bool: ...

    def reset_claimed_to_pending(
        self, task_ids: list[int], claim_token: str = ""
    ) -> int: ...

    def batch_running(self) -> int: ...
