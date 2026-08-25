from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

X_ANCHOR_TZ = ZoneInfo("Asia/Shanghai")
X_ANCHOR_HOUR = 8
X_CACHE_SUFFIX = "_0800_x"


def x_anchor_datetime(anchor_date: str) -> datetime:
    """Return the fixed anchor moment (08:00 Asia/Shanghai) for a date string."""
    return datetime(
        *map(int, anchor_date.split("-")),
        X_ANCHOR_HOUR,
        0,
        0,
        tzinfo=X_ANCHOR_TZ,
    )


def x_rolling_window_bounds(
    anchor_date: str,
) -> tuple[datetime, datetime]:
    """Return the half-open 24h window ending at the anchor moment.

    The window is [anchor - 24h, anchor). For the 08:00 CST anchor this means
    tweets published from 08:00 yesterday up to (but not including) 08:00 today.
    """
    anchor = x_anchor_datetime(anchor_date)
    return (anchor - timedelta(hours=24), anchor)


def x_briefing_cache_date(anchor_date: str) -> str:
    """Cache key segment for the fixed-anchor X briefing."""
    return f"{anchor_date}{X_CACHE_SUFFIX}"
