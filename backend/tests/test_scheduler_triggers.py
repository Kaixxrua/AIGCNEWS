from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.app.core.scheduler_triggers import DailyWindowIntervalTrigger

SHANGHAI = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")


def _at(hour: int, minute: int, tz: ZoneInfo = SHANGHAI, *, day: int = 5, month: int = 8, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=tz)


def test_constructor_rejects_invalid_window_and_interval() -> None:
    with pytest.raises(ValueError, match="interval_minutes"):
        DailyWindowIntervalTrigger(
            start_time=time(0, 0),
            end_time=time(1, 0),
            interval_minutes=0,
        )

    with pytest.raises(ValueError, match="start_time"):
        DailyWindowIntervalTrigger(
            start_time=time(12, 0),
            end_time=time(8, 0),
            interval_minutes=30,
        )


def test_str_and_repr_describe_window() -> None:
    trigger = DailyWindowIntervalTrigger(
        start_time=time(8, 0),
        end_time=time(20, 0),
        interval_minutes=90,
        timezone=SHANGHAI,
    )
    assert "daily-window[08:00:00-20:00:00 every 90m]" == str(trigger)
    assert "DailyWindowIntervalTrigger" in repr(trigger)
    assert "interval_minutes=90" in repr(trigger)


def test_first_fire_at_window_start() -> None:
    trigger = DailyWindowIntervalTrigger(
        start_time=time(8, 0),
        end_time=time(20, 0),
        interval_minutes=60,
        timezone=SHANGHAI,
    )
    now = _at(7, 30)
    assert trigger.get_next_fire_time(None, now) == _at(8, 0)


def test_next_fire_follows_interval_from_start() -> None:
    trigger = DailyWindowIntervalTrigger(
        start_time=time(8, 0),
        end_time=time(20, 0),
        interval_minutes=90,
        timezone=SHANGHAI,
    )
    previous = _at(8, 0)
    now = _at(9, 30)
    assert trigger.get_next_fire_time(previous, now) == _at(9, 30)


def test_next_fire_skips_past_occurrences_before_now() -> None:
    trigger = DailyWindowIntervalTrigger(
        start_time=time(8, 0),
        end_time=time(20, 0),
        interval_minutes=60,
        timezone=SHANGHAI,
    )
    previous = _at(8, 0)
    now = _at(11, 15)
    assert trigger.get_next_fire_time(previous, now) == _at(12, 0)


def test_fire_at_end_time_is_allowed() -> None:
    trigger = DailyWindowIntervalTrigger(
        start_time=time(8, 0),
        end_time=time(20, 0),
        interval_minutes=60,
        timezone=SHANGHAI,
    )
    previous = _at(19, 0)
    now = _at(19, 30)
    assert trigger.get_next_fire_time(previous, now) == _at(20, 0)


def test_after_window_rolls_to_next_day_start() -> None:
    trigger = DailyWindowIntervalTrigger(
        start_time=time(8, 0),
        end_time=time(20, 0),
        interval_minutes=60,
        timezone=SHANGHAI,
    )
    previous = _at(20, 0)
    now = _at(20, 1)
    assert trigger.get_next_fire_time(previous, now) == _at(8, 0, day=6)


def test_pickle_round_trip_preserves_fields() -> None:
    trigger = DailyWindowIntervalTrigger(
        start_time=time(8, 0),
        end_time=time(20, 0),
        interval_minutes=90,
        timezone=SHANGHAI,
    )
    state = trigger.__getstate__()
    restored = DailyWindowIntervalTrigger.__new__(DailyWindowIntervalTrigger)
    restored.__setstate__(state)

    assert restored.start_time == trigger.start_time
    assert restored.end_time == trigger.end_time
    assert restored.interval == timedelta(minutes=90)
    assert str(restored.timezone) == "Asia/Shanghai"


def test_utc_timezone_conversion() -> None:
    trigger = DailyWindowIntervalTrigger(
        start_time=time(8, 0),
        end_time=time(20, 0),
        interval_minutes=60,
        timezone=UTC,
    )
    now = datetime(2026, 8, 5, 7, 30, tzinfo=UTC)
    assert trigger.get_next_fire_time(None, now) == datetime(2026, 8, 5, 8, 0, tzinfo=UTC)


def test_very_short_window_with_long_interval_still_fires_once() -> None:
    trigger = DailyWindowIntervalTrigger(
        start_time=time(2, 0),
        end_time=time(2, 1),
        interval_minutes=1440,
        timezone=SHANGHAI,
    )
    previous = _at(2, 1)
    now = _at(3, 0)
    assert trigger.get_next_fire_time(previous, now) == _at(2, 0, day=6)
