"""Reviewed historical GitHub daily-board quality (2026-10-15 audit).

These decisions affect presentation only: retain observations and metrics for
repair. Re-enable a date only after verifying genuine historical observations;
neither today's star count nor a backfill timestamp establishes past growth.
See docs/github-board-quality.md for the evidence and recovery contract.
"""
from __future__ import annotations

from datetime import date
from typing import Literal, TypedDict


class BoardDataQuality(TypedDict):
    status: Literal["available", "partial", "unavailable"]
    reason: str | None


_UNAVAILABLE = {
    "2026-07-09": "baseline_missing",
    "2026-07-10": "observation_window",
    "2026-07-12": "missing",
    "2026-07-13": "sparse",
    "2026-07-14": "baseline_missing",
    "2026-07-23": "observation_window",
    "2026-08-09": "backfill_unverified",
    "2026-09-07": "observation_window",
    "2026-09-08": "missing",
    "2026-09-09": "sparse",
    "2026-09-12": "observation_window",
    "2026-09-13": "backfill_unverified",
    "2026-09-14": "backfill_unverified",
    "2026-09-15": "backfill_unverified",
}
_PARTIAL = {
    "2026-07-19": "coverage_partial",
    "2026-07-20": "coverage_partial",
    "2026-07-21": "cross_day_growth",
    "2026-08-10": "cross_day_growth",
    "2026-08-18": "window_partial",
    "2026-08-26": "window_partial",
    "2026-08-27": "window_partial",
    "2026-09-10": "cross_day_growth",
    "2026-09-16": "cross_day_growth",
    "2026-10-09": "coverage_partial",
}


def github_board_quality(snapshot_date: str) -> BoardDataQuality:
    try:
        historical = date.fromisoformat(snapshot_date) < date(2026, 7, 9)
    except ValueError:
        historical = False
    if historical:
        return {"status": "unavailable", "reason": "historical_unavailable"}
    if snapshot_date in _UNAVAILABLE:
        return {"status": "unavailable", "reason": _UNAVAILABLE[snapshot_date]}
    if snapshot_date in _PARTIAL:
        return {"status": "partial", "reason": _PARTIAL[snapshot_date]}
    # Expansion days (08-03/08-11), trustworthy rolling growth (10-10), and
    # unaudited/current dates are not suppressed by heuristic row thresholds.
    return {"status": "available", "reason": None}
