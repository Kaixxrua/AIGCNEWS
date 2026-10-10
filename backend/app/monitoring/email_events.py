"""Best-effort mail audit; never store addresses, subjects, bodies or OTPs."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

_writer: Callable[[str, str, str | None], None] | None = None
logger = logging.getLogger(__name__)


def configure_email_event_writer(writer: Callable | None) -> None:
    global _writer
    _writer = writer


async def record_email_event(kind: str, outcome: str, error_type: str | None = None) -> None:
    if _writer is not None:
        try:
            await asyncio.to_thread(_writer, kind, outcome, error_type)
        except Exception:
            # A monitoring outage must never turn an accepted OTP into a
            # delivery failure and cause an unsafe resend.
            logger.warning("[EmailMonitor] audit write failed", exc_info=True)
