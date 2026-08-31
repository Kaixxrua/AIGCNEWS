from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

_VISITOR_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_CST = timezone(timedelta(hours=8))
_KEY_PREFIX = "aigc:site-visitor-ids:"


class InvalidVisitorId(ValueError):
    """Raised when a client-supplied anonymous visitor ID is malformed."""


def validate_visitor_id(visitor_id: str) -> str:
    value = visitor_id.strip()
    if not _VISITOR_ID_PATTERN.fullmatch(value):
        raise InvalidVisitorId("visitor_id must be 16-128 safe identifier characters")
    return value


def visitor_set_key(day: date) -> str:
    return f"{_KEY_PREFIX}{day.isoformat()}"


def seconds_until_next_cst_day(now: datetime | None = None) -> int:
    current = now.astimezone(_CST) if now is not None else datetime.now(_CST)
    next_day = datetime.combine(
        current.date() + timedelta(days=1), datetime.min.time(), tzinfo=_CST
    )
    return max(1, int((next_day - current).total_seconds()))


async def mark_new_daily_visitor(
    redis_client: Any,
    *,
    day: date,
    visitor_id: str,
) -> bool:
    """Atomically mark an ID for a CST day and return whether it was new.

    Redis owns only short-lived anonymous IDs. The key expires at the next CST
    midnight, so no scheduled deletion or per-ID database row is required.
    """
    identifier = validate_visitor_id(visitor_id)
    key = visitor_set_key(day)
    added = int(await redis_client.sadd(key, identifier))
    ttl = int(await redis_client.ttl(key))
    if ttl < 0:
        await redis_client.expire(key, seconds_until_next_cst_day())
    return added == 1
