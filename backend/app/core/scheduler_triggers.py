from __future__ import annotations

from datetime import datetime, time, timedelta, tzinfo
from typing import Any

from apscheduler.triggers.base import BaseTrigger
from apscheduler.util import astimezone


class DailyWindowIntervalTrigger(BaseTrigger):
    """Trigger that fires every ``interval_minutes`` inside a daily time window.

    The window is defined by ``start_time`` and ``end_time`` in the given timezone.
    Fires are inclusive of the start instant and continue until ``end_time`` is
    reached; after the window closes, scheduling resumes at the start of the next
    day.
    """

    __slots__ = ("start_time", "end_time", "interval", "timezone", "_interval")

    def __init__(
        self,
        *,
        start_time: time,
        end_time: time,
        interval_minutes: int,
        timezone: tzinfo | str | None = None,
    ) -> None:
        if interval_minutes <= 0:
            raise ValueError("interval_minutes 必须大于 0")
        if start_time > end_time:
            raise ValueError("start_time 不能晚于 end_time")

        self.timezone = astimezone(timezone) if timezone else astimezone()
        self.start_time = start_time
        self.end_time = end_time
        self.interval = timedelta(minutes=interval_minutes)

    def get_next_fire_time(
        self,
        previous_fire_time: datetime | None,
        now: datetime,
    ) -> datetime | None:
        tz = self.timezone
        now = now.astimezone(tz)

        base_date = now.date()
        start = datetime.combine(base_date, self.start_time, tz)
        end = datetime.combine(base_date, self.end_time, tz)

        if previous_fire_time is not None:
            candidate = previous_fire_time.astimezone(tz) + self.interval
        else:
            candidate = start

        # If the candidate is before the current window, snap forward to the first
        # fire time that is not earlier than ``now``.
        if candidate < start:
            candidate = start

        if candidate <= end:
            delta = candidate - start
            if delta < timedelta(0):
                # Candidate still earlier than today's start; should not happen after
                # the snap above, but keep the arithmetic safe.
                candidate = start
            else:
                steps = (delta.total_seconds() // self.interval.total_seconds())
                candidate = start + self.interval * steps
                while candidate < now:
                    candidate += self.interval

        if candidate > end:
            # Roll over to the start of the next day.
            next_day = base_date + timedelta(days=1)
            candidate = datetime.combine(next_day, self.start_time, tz)

        return candidate

    def __getstate__(self) -> dict[str, Any]:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "interval_minutes": int(self.interval.total_seconds() // 60),
            "timezone": self.timezone,
        }

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.start_time = state["start_time"]
        self.end_time = state["end_time"]
        self.interval = timedelta(minutes=state["interval_minutes"])
        self.timezone = astimezone(state["timezone"])

    def __str__(self) -> str:
        return (
            f"daily-window[{self.start_time.isoformat()}-"
            f"{self.end_time.isoformat()} every {int(self.interval.total_seconds() // 60)}m]"
        )

    def __repr__(self) -> str:
        return (
            f"DailyWindowIntervalTrigger(start_time={self.start_time!r}, "
            f"end_time={self.end_time!r}, "
            f"interval_minutes={int(self.interval.total_seconds() // 60)}, "
            f"timezone={self.timezone!r})"
        )
