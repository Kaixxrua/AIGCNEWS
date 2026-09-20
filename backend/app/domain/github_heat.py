"""Time-normalized GitHub heat; daily observed growth remains a separate metric."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

SCORE_VERSION = "daily_hot_v6"
DISPLAY_ANCHORS = ((0, 0), (20, 25), (40, 45), (60, 65), (70, 77),
                   (80, 85), (85, 90), (90, 93), (95, 96), (100, 100))


def display_score(raw: float) -> float:
    for (lower, start), (upper, end) in zip(DISPLAY_ANCHORS, DISPLAY_ANCHORS[1:]):
        if raw <= upper:
            return max(0.0, start + (end - start) * (raw - lower) / (upper - lower))
    return 100.0


def _speed(a: dict, b: dict, field: str) -> float | None:
    hours = b["t"] - a["t"]
    if not 0 < hours <= 48:
        return None
    if field != "stars" and not (a.get("community_metrics_complete") and b.get("community_metrics_complete")):
        return None
    return max(float(b.get(field) or 0) - float(a.get(field) or 0), 0) * 24 / hours


def _blend(current: float | None, previous: float | None, hours: float) -> float | None:
    weight = min(hours / 12, 1)
    if current is None or (weight < 1 and previous is None):
        return None
    return weight * current + (1 - weight) * (previous or 0)


def _normalize(raw: float, reference: float) -> float:
    return 100 * min(max(raw / reference, 0), 1)


def _trend(growth: float, baseline: float) -> float:
    if growth <= 0:
        return 0.0
    ratio = (growth + 20) / (baseline + 20)
    anchors = ((0.25, 0), (0.5, 20), (1, 60), (2, 85), (4, 100))
    if ratio <= 0.25:
        return 0.0
    for (lower, start), (upper, end) in zip(anchors, anchors[1:]):
        if ratio <= upper:
            return start + (end - start) * math.log(ratio / lower) / math.log(upper / lower)
    return 100.0


def score_snapshots(history: list[dict[str, Any]], metric_date: str) -> dict[str, Any] | None:
    """Return v6 components, or None when reliable rate inputs are unavailable.

    Uses only the requested slice and older observations. No wall-clock state,
    previous score, or future slice participates, so historical reruns are stable.
    """
    snapshots = []
    for item in history:
        try:
            observed = datetime.fromisoformat(str(item.get("captured_at") or ""))
            labelled = date.fromisoformat(str(item["snapshot_date"]))
        except (ValueError, KeyError):
            continue
        if observed.tzinfo is None or abs((observed.date() - labelled).days) > 1:
            continue
        if labelled.isoformat() <= metric_date:
            snapshots.append({**item, "t": observed.timestamp() / 3600})
    current = [s for s in snapshots if str(s["snapshot_date"]) == metric_date]
    if not current:
        return None
    s = max(current, key=lambda x: x["t"])
    earlier = sorted((p for p in snapshots if str(p["snapshot_date"]) < metric_date and p["t"] < s["t"]), key=lambda x: x["t"])
    if not earlier:
        return None
    p = earlier[-1]
    if str(p["snapshot_date"]) != (date.fromisoformat(metric_date) - timedelta(days=1)).isoformat():
        return None
    hours = s["t"] - p["t"]
    q = earlier[-2] if len(earlier) > 1 else None
    growth = _blend(_speed(p, s, "stars"), _speed(q, p, "stars") if q else None, hours)
    if growth is None:
        return None

    total = baseline_hours = 0.0
    for a, b in zip(earlier, earlier[1:]):
        overlap = max(0, min(b["t"], p["t"]) - max(a["t"], p["t"] - 168))
        rate = _speed(a, b, "stars")
        if rate is not None and overlap:
            total += rate * overlap / 24
            baseline_hours += overlap
    baseline = total * 24 / baseline_hours if baseline_hours else 0.0
    scale = _normalize(math.log1p(growth / math.sqrt(max(float(p.get("stars") or 0), 500))), math.log(5))
    absolute = _normalize(math.log1p(growth), math.log(1001))
    trend = _trend(growth, baseline) * min(baseline_hours / 72, 1)
    fork, watcher = (
        _blend(_speed(p, s, field), _speed(q, p, field) if q else None, hours)
        for field in ("forks", "watchers")
    )
    community = (
        _normalize(0.6 * math.log1p(fork) + 0.4 * math.log1p(watcher), 0.6 * math.log(101) + 0.4 * math.log(11))
        if fork is not None and watcher is not None else 0.0
    )
    try:
        days = max((date.fromisoformat(metric_date) - date.fromisoformat(str(s.get("repo_pushed_at") or "")[:10])).days, 0)
        maintenance = 100 / (1 + days / 14)
    except ValueError:
        maintenance = 0.0
    raw = 0.5 * scale + 0.3 * absolute + 0.1 * trend + 0.05 * community + 0.05 * maintenance
    return {
        "scale_corrected_growth_score": round(scale, 4),
        "absolute_growth_score": round(absolute, 4),
        "growth_acceleration_score": round(trend, 4),
        "community_engagement_score": round(community, 4),
        "maintenance_activity_score": round(maintenance, 4),
        "hot_score": round(display_score(raw), 4),
        "score_version": SCORE_VERSION,
    }
