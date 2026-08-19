from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class XTranslationStatusResponse(BaseModel):
    pending: int = 0
    running: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    retryable: int = 0
    stale_running: int = 0
    oldest_pending_at: datetime | None = None
    latest_failure_at: datetime | None = None
    latest_failure_error: str | None = None
    latest_failure_model_provider: str | None = None
    latest_failure_model_name: str | None = None
    latest_failure_prompt_version: str | None = None
    batch_running: int = 0


class XTranslationRetryRequest(BaseModel):
    limit: int = Field(default=200, ge=1, le=500)
    concurrency: int = Field(default=3, ge=1, le=10)


class XTranslationRetryResponse(BaseModel):
    status: str
    message: str
    result: dict[str, Any] | None = None
