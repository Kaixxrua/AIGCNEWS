"""Bounded internal generation evidence without exception messages or inputs."""
from __future__ import annotations

import asyncio
import re
import time
import traceback
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import PurePath

_VALIDATION_REASONS = frozenset({"invalid_type", "empty", "too_long", "no_han", "kana_present", "identity_conflict"})


def _identifier(value: str, fallback: str) -> str:
    return value if re.fullmatch(r"[A-Za-z0-9_.<>-]{1,100}", value) else fallback


@asynccontextmanager
async def generation_stage(trace: list[dict], stage: str):
    """Record only code-owned stage names, timing and safe exception metadata."""
    record = {"stage": stage, "at": datetime.now(UTC).isoformat()}
    started = time.monotonic()
    try:
        yield
    except BaseException as exc:
        record.update(status="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                      errorType=_identifier(type(exc).__name__, "Exception"))
        record["errorFrames"] = [
            {"file": _identifier(PurePath(frame.filename).name, "unknown"),
             "function": _identifier(frame.name, "unknown"), "line": frame.lineno}
            for frame in traceback.extract_tb(exc.__traceback__)[-3:]
        ]
        # Some SDKs store the HTTP status directly, others on a response.
        # Never serialize response/request objects, their headers, or messages.
        status = getattr(exc, "status_code", None)
        if status is None:
            status = getattr(getattr(exc, "response", None), "status_code", None)
        if type(status) is int and 100 <= status <= 599:
            record["httpStatus"] = status
        reason = getattr(exc, "validation_reason", None)
        if isinstance(reason, str) and reason in _VALIDATION_REASONS:
            record["validationReason"] = reason
        raise
    else:
        record["status"] = "succeeded"
    finally:
        record["elapsedMs"] = round((time.monotonic() - started) * 1000)
        trace.append(record)
