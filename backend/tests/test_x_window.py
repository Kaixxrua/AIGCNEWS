from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from backend.app.services.briefing.x_window import (
    X_ANCHOR_HOUR,
    X_ANCHOR_TZ,
    x_anchor_datetime,
    x_briefing_cache_date,
    x_rolling_window_bounds,
)


class XWindowTests(unittest.TestCase):
    def test_anchor_datetime_is_0800_cst(self) -> None:
        anchor = x_anchor_datetime("2026-07-22")
        self.assertEqual(
            anchor,
            datetime(2026, 7, 22, X_ANCHOR_HOUR, 0, 0, tzinfo=X_ANCHOR_TZ),
        )

    def test_rolling_window_is_half_open_24h(self) -> None:
        start, end = x_rolling_window_bounds("2026-07-22")
        self.assertEqual(end, x_anchor_datetime("2026-07-22"))
        self.assertEqual(start, end - timedelta(hours=24))
        self.assertEqual(start, datetime(2026, 7, 21, 8, 0, 0, tzinfo=X_ANCHOR_TZ))

    def test_rolling_window_crosses_month_boundary(self) -> None:
        start, end = x_rolling_window_bounds("2026-03-01")
        self.assertEqual(start.day, 28)
        self.assertEqual(start.month, 2)
        self.assertEqual(end.day, 1)
        self.assertEqual(end.month, 3)

    def test_cache_date_includes_anchor_marker(self) -> None:
        self.assertEqual(
            x_briefing_cache_date("2026-07-22"),
            "2026-07-22_0800_x",
        )

    def test_anchor_datetime_invalid_date_raises(self) -> None:
        with self.assertRaises(ValueError):
            x_anchor_datetime("not-a-date")


if __name__ == "__main__":
    unittest.main()
