"""GitHub heat v11: rolling 24-hour growth with bounded top-ten rotation.

Magnitude (scale-corrected plus absolute star velocity) decides the ranking;
trend, community and maintenance only modulate it, so a saturated magnitude can
no longer hand the top of the board to secondary signals. Missing inputs are
unknown, not zero: without baseline history the trend is neutral, and missing
community or maintenance observations drop out of the quality average. Daily
observed deltas and suspicion signals keep their own contracts.

v8 measures growth over the trailing 24 hours instead of the calendar day, so
the board no longer resets at midnight. A repository counts from zero stars at
creation: newborns score the stars gathered since creation, and repositories
under a week old interpolate from that origin until real observations cover the
window. A fading virtual stock keeps a newborn's first hundred stars from
reading like a breakout, and absolute growth keeps rising past 10k stars/day.

v11 discounts repeated top-ten exposure by 4% per prior appearance, capped at
20%. Three consecutive days outside the top ten reset the count; shorter gaps
pause it. Only prior daily boards count.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

SCORE_VERSION = "daily_hot_v11"

TOP_STREAK_RANK_LIMIT = 10
TOP_STREAK_PRIOR_DAYS_CAP = 5
TOP_STREAK_RESET_DAYS = 3
# Five appearances separated by at most two off-board days reach the cap.
TOP_STREAK_LOOKBACK_DAYS = TOP_STREAK_PRIOR_DAYS_CAP * TOP_STREAK_RESET_DAYS
TOP_STREAK_GRACE_DAYS = 1
TOP_STREAK_PENALTY_STEP = 0.04
TOP_STREAK_PENALTY_CAP = 0.20

MIN_SCALE_STARS = 500
# Full marks sit near the historical daily peaks (top x≈15–110, top g≈2k–6.5k),
# far above p99.9 (x≈10.6, g≈913), so ordinary top days no longer saturate.
SCALE_REFERENCE = 100.0  # stars/day ÷ √stars
ABSOLUTE_REFERENCE = 10000.0  # stars/day
# Below the reference the absolute term is unchanged; beyond it keeps rising
# (unclamped) until the ceiling, and magnitude itself is capped at 100.
ABSOLUTE_CEILING = 100000.0  # stars/day
# Launch expectation: a newborn is judged as if it already held this many
# stars, halving every day, so it falls back to MIN_SCALE_STARS within ~16h.
LAUNCH_VIRTUAL_STARS = 800.0
LAUNCH_HALF_LIFE_DAYS = 1.0
ROLLING_WINDOW_HOURS = 24
# Repositories younger than this may use (created_at, 0 stars) as the window
# start when no real observation precedes it.
CREATION_ORIGIN_DAYS = 7
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
    age_days: float | None = None  # repository age at the measurement


@dataclass(frozen=True)
class RollingGrowth:
    """Growth over the trailing window ending at the latest snapshot."""

    star_growth: float
    base_stars: float  # stars at the window start (0 for newborns)
    fork_growth: float | None  # None when fork counts are not trustworthy
    source: str  # rolling_window | creation_interpolated | since_creation
    observed_at: datetime  # window end
    age_days: float | None


def parse_timestamp(value: Any) -> datetime | None:
    """ISO timestamp → aware datetime; date-only values read as UTC midnight."""
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


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


def _interpolate(lo: tuple[datetime, float], hi: tuple[datetime, float], at: datetime) -> float:
    span = (hi[0] - lo[0]).total_seconds()
    if span <= 0:
        return hi[1]
    return lo[1] + (hi[1] - lo[1]) * (at - lo[0]).total_seconds() / span


def rolling_growth(
    history: list[dict[str, Any]],
    metric_date: str,
    *,
    observations: Iterable[dict[str, Any]] = (),
    created_at: Any = None,
) -> RollingGrowth | None:
    """Stars gained over the trailing window that ends at the latest snapshot.

    The window start is interpolated between the last point at or before it
    and the first point after it. Points are daily snapshots (same validation
    as snapshot_velocity), intraday star observations, and — for repositories
    under CREATION_ORIGIN_DAYS — the origin (created_at, 0 stars). Newborns
    younger than the window score everything since creation, never an
    extrapolated daily rate. Only the requested slice and older data take
    part, so historical reruns are stable. Returns None without a usable start.
    """
    snapshots: list[dict[str, Any]] = []
    for item in history:
        try:
            observed = datetime.fromisoformat(str(item.get("captured_at") or ""))
            labelled = date.fromisoformat(str(item["snapshot_date"]))
        except (ValueError, KeyError):
            continue
        if observed.tzinfo is None or abs((observed.date() - labelled).days) > 1:
            continue
        if labelled.isoformat() <= metric_date:
            snapshots.append({**item, "_t": observed})
    current = [s for s in snapshots if str(s["snapshot_date"]) == metric_date]
    if not current:
        return None
    end_point = max(current, key=lambda s: s["_t"])
    end = end_point["_t"]
    stars_now = float(end_point.get("stars") or 0)
    forks_now = float(end_point.get("forks") or 0) if end_point.get("community_metrics_complete") else None
    created = parse_timestamp(created_at)
    age_days = (end - created).total_seconds() / 86400 if created is not None and created <= end else None
    start = end - timedelta(hours=ROLLING_WINDOW_HOURS)
    if created is not None and start < created <= end:
        return RollingGrowth(
            star_growth=max(stars_now, 0.0),
            base_stars=0.0,
            fork_growth=forks_now,
            source="since_creation",
            observed_at=end,
            age_days=age_days,
        )

    # (time, stars, forks-or-None, is_origin)
    points: list[tuple[datetime, float, float | None, bool]] = []
    for s in snapshots:
        if s["_t"] <= end:
            forks = float(s.get("forks") or 0) if s.get("community_metrics_complete") else None
            points.append((s["_t"], float(s.get("stars") or 0), forks, False))
    for item in observations:
        observed = parse_timestamp(item.get("observed_at"))
        if observed is None or observed > end or item.get("stars") is None:
            continue
        # watchers are only recorded alongside a complete community read
        forks = float(item["forks"]) if item.get("forks") is not None and item.get("watchers") is not None else None
        points.append((observed, float(item["stars"]), forks, False))
    if age_days is not None and age_days < CREATION_ORIGIN_DAYS:
        points.append((created, 0.0, 0.0, True))
    oldest = end - timedelta(days=MAX_GAP_DAYS + 1)
    before = [p for p in points if oldest <= p[0] <= start]
    after = [p for p in points if start < p[0] <= end]
    if not before or not after:
        return None
    lo = max(before, key=lambda p: (p[0], not p[3]))
    hi = min(after, key=lambda p: p[0])
    base = max(_interpolate((lo[0], lo[1]), (hi[0], hi[1]), start), 0.0)
    fork_growth = None
    if lo[2] is not None and hi[2] is not None and forks_now is not None:
        fork_growth = max(forks_now - _interpolate((lo[0], lo[2]), (hi[0], hi[2]), start), 0.0)
    return RollingGrowth(
        star_growth=max(stars_now - base, 0.0),
        base_stars=base,
        fork_growth=fork_growth,
        source="creation_interpolated" if lo[3] else "rolling_window",
        observed_at=end,
        age_days=age_days,
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


def launch_stars(age_days: float | None) -> float:
    if age_days is None:
        return 0.0
    return LAUNCH_VIRTUAL_STARS * 0.5 ** (max(age_days, 0.0) / LAUNCH_HALF_LIFE_DAYS)


def heat_growth_sql(alias: str) -> str:
    """热度所用星增的 SQL 口径：滚动 24h 优先，缺失时退回可用的日增量。

    与指标计算里的取数一致；榜单的正增长筛选和同分排序都要用它，否则只有
    滚动增长的仓库算出了热度却进不了榜。取不到任何增长时为 NULL。
    """
    return (
        f"COALESCE({alias}.rolling_24h_star_growth,"
        f"CASE WHEN {alias}.daily_growth_available THEN {alias}.daily_star_growth END)"
    )


def top_streak_multiplier(previous_top_streak_days: int) -> float:
    extra_days = max(previous_top_streak_days + 1 - TOP_STREAK_GRACE_DAYS, 0)
    return 1 - min(extra_days * TOP_STREAK_PENALTY_STEP, TOP_STREAK_PENALTY_CAP)


def score_heat(
    inputs: HeatInputs, *, suspicion: float = 0.0, previous_top_streak_days: int = 0,
) -> dict[str, Any]:
    growth = max(inputs.star_velocity, 0.0)
    scale = _normalize(
        math.log1p(growth / math.sqrt(max(inputs.base_stars, MIN_SCALE_STARS, launch_stars(inputs.age_days)))),
        math.log1p(SCALE_REFERENCE),
    )
    absolute = 100 * min(math.log1p(growth), math.log1p(ABSOLUTE_CEILING)) / math.log1p(ABSOLUTE_REFERENCE)
    magnitude = min(MAGNITUDE_WEIGHTS["scale"] * scale + MAGNITUDE_WEIGHTS["absolute"] * absolute, 100.0)

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
    previous_top_streak_days = min(max(previous_top_streak_days, 0), TOP_STREAK_PRIOR_DAYS_CAP)
    hot *= top_streak_multiplier(previous_top_streak_days)
    return {
        "scale_corrected_growth_score": round(scale, 4),
        "absolute_growth_score": round(absolute, 4),
        "growth_acceleration_score": round(trend, 4),
        "community_engagement_score": round(community or 0.0, 4),
        "maintenance_activity_score": round(maintenance or 0.0, 4),
        "hot_score": round(hot, 4),
        "previous_top_streak_days": previous_top_streak_days,
        "score_version": SCORE_VERSION,
    }
