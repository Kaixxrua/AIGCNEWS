"""Generate due personal digests and send only to an explicitly selected channel."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from backend.app.repositories.postgres_tracking_repository import PostgresTrackingRepository
from backend.app.services.tracking.content import render_digest

logger = logging.getLogger(__name__)


async def dispatch_tracking(
    repository: PostgresTrackingRepository, sender: Any, *, now: datetime | None = None,
) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    summary = {"generated": 0, "sent": 0, "failed": 0}
    after = 0
    while users := await asyncio.to_thread(repository.due_users, now, after):
        for user_id in users:
            try:
                digest = await asyncio.to_thread(repository.generate_digest, user_id, now)
                summary["generated"] += int(digest is not None)
            except Exception:
                summary["failed"] += 1
                logger.exception("Personal digest generation failed for user_id=%s", user_id)
        after = users[-1]
    # Bound a scheduler pass; subsequent runs continue draining pending delivery.
    for _ in range(500):
        digest = await asyncio.to_thread(repository.claim_delivery, now)
        if digest is None:
            break
        if digest.get("cancelled"):
            continue
        sent = False
        try:
            await sender.send_personal_digest(
                channel=digest["channel"], content=render_digest(digest), issue_date=str(digest["issue_date"]),
            )
            sent = True
        except Exception:
            # Provider exceptions may contain webhook credentials: log IDs only.
            logger.warning("Personal digest delivery failed for digest_id=%s", digest["id"])
        await asyncio.to_thread(repository.finish_delivery, digest["id"], digest["attempts"], sent=sent)
        summary["sent" if sent else "failed"] += 1
    return summary
