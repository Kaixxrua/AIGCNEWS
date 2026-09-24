"""GitHub heat v7: one scale for every row with observed star growth.

Magnitude (scale-corrected plus absolute star velocity) decides the ranking;
trend, community and maintenance only modulate it, so a saturated magnitude can
no longer hand the top of the board to secondary signals. Missing inputs are
unknown, not zero: without baseline history the trend is neutral, and missing
community or maintenance observations drop out of the quality average. Daily
observed deltas and suspicion signals keep their own contracts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

SCORE_VERSION = "daily_hot_v7"

MIN_SCALE_STARS = 500
# Full marks sit near the historical daily peaks (top x≈15–110, top g≈2k–6.5k),
# far above p99.9 (x≈10.6, g≈913), so ordinary top days no longer saturate.
SCALE_REFERENCE = 100.0  # stars/day ÷ √stars
ABSOLUTE_REFERENCE = 10000.0  # stars/day
MAGNITUDE_WEIGHTS = {"scale": 0.625, "absolute": 0.375}
QUALITY_WEIGHTS = {"trend": 0.5, "community": 0.25, "maintenance": 0.25}
# hot = magnitude × (QUALITY_BASE + QUALITY_SPAN × quality / 100)
QUALITY_BASE = 0.8
QUALITY_SPAN = 0.2
TREND_NEUTRAL = 60.0
TREND_ANCHORS = ((0.25, 0.0), (0.5, 20.0), (1.0, 60.0), (2.0, 85.0), (4.0, 100.0))
TREND_FULL_CONFIDENCE_HOURS = 72
COMMUNITY_REFERENCE = 0.6 * math.log(101) + 0.4 * math.log(11)
# Two or more independent signals (e.g. no fork follow on a fresh repo) demote;
# a single signal only tags, since some audiences fork rarely.
SUSPICION_DEMOTION_THRESHOLD = 0.5
SUSPICION_DEMOTION_STRENGTH = 0.6
BLEND_HOURS = 12
MAX_GAP_DAYS = 7


@dataclass(frozen=True)
class HeatInputs:
    star_velocity: float  # stars per day
    base_stars: float  # stars before the measured interval
    baseline_velocity: float | None = None  # prior 7-day stars per day
    baseline_confidence: float = 0.0  # 0..1
    fork_velocity: float | None = None
    watcher_velocity: float | None = None
    days_since_push: int | None = None


def days_since(metric_date: str, pushed_at: Any) -> int | None:
    try:
        pushed = date.fromisoformat(str(pushed_at or "")[:10])
        return max((date.fromisoformat(metric_date) - pushed).days, 0)
    except ValueError:
        return None


def _rate(a: dict, b: dict, field: str) -> float | None:
    hours = b["t"] - a["t"]
    if not 0 < hours <= (MAX_GAP_DAYS + 1) * 24:
        return None
    if field != "stars" and not (a.get("community_metrics_complete") and b.get("community_metrics_complete")):
        return None
    return max(float(b.get(field) or 0) - float(a.get(field) or 0), 0) * 24 / hours


def _blend(current: float | None, previous: float | None, hours: float) -> float | None:
    """Lean on the preceding interval while the current one is short."""
    if current is None or previous is None:
        return current
    weight = min(hours / BLEND_HOURS, 1)
    return weight * current + (1 - weight) * previous


def snapshot_velocity(history: list[dict[str, Any]], metric_date: str) -> HeatInputs | None:
    """Estimate velocities from the requested slice and older observations.

    No wall-clock state, previous score, or future slice participates, so
    historical reruns are stable. Returns None without a usable interval.
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
    oldest = (date.fromisoformat(metric_date) - timedelta(days=MAX_GAP_DAYS)).isoformat()
    if not earlier or str(earlier[-1]["snapshot_date"]) < oldest:
        return None
    p = earlier[-1]
    q = earlier[-2] if len(earlier) > 1 else None
    hours = s["t"] - p["t"]
    stars, forks, watchers = (
        _blend(_rate(p, s, field), _rate(q, p, field) if q else None, hours)
        for field in ("stars", "forks", "watchers")
    )
    if stars is None:
        return None

    total = baseline_hours = 0.0
    for a, b in zip(earlier, earlier[1:]):
        overlap = max(0, min(b["t"], p["t"]) - max(a["t"], p["t"] - 168))
        rate = _rate(a, b, "stars")
        if rate is not None and overlap:
            total += rate * overlap / 24
            baseline_hours += overlap
    return HeatInputs(
        star_velocity=stars,
        base_stars=float(p.get("stars") or 0),
        baseline_velocity=total * 24 / baseline_hours if baseline_hours else None,
        baseline_confidence=min(baseline_hours / TREND_FULL_CONFIDENCE_HOURS, 1),
        fork_velocity=forks,
        watcher_velocity=watchers,
        days_since_push=days_since(metric_date, s.get("repo_pushed_at")),
    )


def _normalize(raw: float, reference: float) -> float:
    return 100 * min(max(raw / reference, 0), 1)


def _trend_curve(growth: float, baseline: float) -> float:
    ratio = (growth + 20) / (max(baseline, 0) + 20)
    if ratio <= TREND_ANCHORS[0][0]:
        return 0.0
    for (lower, start), (upper, end) in zip(TREND_ANCHORS, TREND_ANCHORS[1:]):
        if ratio <= upper:
            return start + (end - start) * math.log(ratio / lower) / math.log(upper / lower)
    return 100.0


def suspicion_multiplier(suspicion: float) -> float:
    if suspicion < SUSPICION_DEMOTION_THRESHOLD:
        return 1.0
    return 1 - SUSPICION_DEMOTION_STRENGTH * min(suspicion, 1.0)


def score_heat(inputs: HeatInputs, *, suspicion: float = 0.0) -> dict[str, Any]:
    growth = max(inputs.star_velocity, 0.0)
    scale = _normalize(
        math.log1p(growth / math.sqrt(max(inputs.base_stars, MIN_SCALE_STARS))),
        math.log1p(SCALE_REFERENCE),
    )
    absolute = _normalize(math.log1p(growth), math.log1p(ABSOLUTE_REFERENCE))
    magnitude = MAGNITUDE_WEIGHTS["scale"] * scale + MAGNITUDE_WEIGHTS["absolute"] * absolute

    trend = 0.0
    if growth > 0:
        confidence = inputs.baseline_confidence if inputs.baseline_velocity is not None else 0.0
        curve = _trend_curve(growth, inputs.baseline_velocity or 0.0)
        trend = confidence * curve + (1 - confidence) * TREND_NEUTRAL
    community = None
    if inputs.fork_velocity is not None and inputs.watcher_velocity is not None:
        community = _normalize(
            0.6 * math.log1p(inputs.fork_velocity) + 0.4 * math.log1p(inputs.watcher_velocity),
            COMMUNITY_REFERENCE,
        )
    maintenance = None if inputs.days_since_push is None else 100 / (1 + inputs.days_since_push / 14)
    known = {
        name: value
        for name, value in (("trend", trend), ("community", community), ("maintenance", maintenance))
        if value is not None
    }
    quality = sum(QUALITY_WEIGHTS[name] * value for name, value in known.items()) / sum(
        QUALITY_WEIGHTS[name] for name in known
    )
    hot = magnitude * (QUALITY_BASE + QUALITY_SPAN * quality / 100) * suspicion_multiplier(suspicion)
    return {
        "scale_corrected_growth_score": round(scale, 4),
        "absolute_growth_score": round(absolute, 4),
        "growth_acceleration_score": round(trend, 4),
        "community_engagement_score": round(community or 0.0, 4),
        "maintenance_activity_score": round(maintenance or 0.0, 4),
        "hot_score": round(hot, 4),
        "score_version": SCORE_VERSION,
    }
