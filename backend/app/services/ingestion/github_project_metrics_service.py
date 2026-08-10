from __future__ import annotations

"""Daily GitHub project metric snapshots and hot-score computation."""

import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from backend.app.core.config import settings
from backend.app.repositories.project_write_repository import (
    GitHubProjectIngestionRepository,
)
from backend.app.services.ingestion.source_github import fetch_github_repo_metrics_batch

logger = logging.getLogger(__name__)

DEFAULT_MIN_STARS = 500
DEFAULT_SCORE_VERSION = "daily_hot_v5"
_FULL_ACCELERATION_CONFIDENCE_SAMPLES = 3
_SCALE_GROWTH_REFERENCE = math.log1p(4.0)
_ABSOLUTE_GROWTH_REFERENCE = math.log1p(1000.0)
_COMMUNITY_REFERENCE = 0.6 * math.log1p(100.0) + 0.4 * math.log1p(10.0)
_ACCELERATION_RATIO_ANCHORS = (
    (0.25, 0.0),
    (0.5, 20.0),
    (1.0, 40.0),
    (2.0, 75.0),
    (4.0, 100.0),
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_now(tz_name: str | None = None) -> datetime:
    timezone_name = tz_name or getattr(settings, "scheduler_timezone", "Asia/Shanghai") or "Asia/Shanghai"
    return datetime.now(ZoneInfo(timezone_name))


def _local_today(tz_name: str | None = None) -> date:
    return _local_now(tz_name).date()


def current_github_metric_date() -> str:
    return _local_today().isoformat()


def _date_str(value: date | str | None = None) -> str:
    if value is None:
        return current_github_metric_date()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _live_metric_date(
    value: date | str | None = None,
    *,
    local_today: date | None = None,
) -> str:
    """Resolve a live GitHub snapshot date and reject historical writes."""
    today = (local_today or _local_today()).isoformat()
    resolved = _date_str(value) if value is not None else today
    try:
        parsed = date.fromisoformat(resolved)
    except ValueError as exc:
        raise ValueError(f"Invalid GitHub metric date: {resolved}") from exc
    if parsed.isoformat() != today:
        raise ValueError(
            f"Live GitHub snapshots can only be written for today ({today}), got {resolved}"
        )
    return today


# 关榜窗口：次日 00:00–01:00（调度时区）。窗口内关榜轮允许写昨日切片，
# 捕获 23:17 末轮常规刷新之后到日界结束的尾巴增长；该快照同时成为
# 今日指标的基线（≤昨日最新），跨日总账不错乱，仅日界归属最多偏移
# 一个关榜窗口。常规（非关榜）路径保持"仅今天"守卫不变。
CLOSING_WINDOW_END_HOUR = 1


def _closing_metric_date(
    value: date | str | None,
    *,
    local_now: datetime,
) -> str:
    """关榜轮日期解析：今天照常放行；昨日仅在关榜窗口内放行。"""
    today = local_now.date()
    resolved = today.isoformat() if value is None else _date_str(value)
    try:
        parsed = date.fromisoformat(resolved)
    except ValueError as exc:
        raise ValueError(f"Invalid GitHub metric date: {resolved}") from exc
    if parsed == today:
        return today.isoformat()
    if (
        parsed == today - timedelta(days=1)
        and local_now.hour < CLOSING_WINDOW_END_HOUR
    ):
        return parsed.isoformat()
    raise ValueError(
        "Closing GitHub snapshots can only be written for today "
        f"({today}) or yesterday within the closing window, got {resolved}"
    )


def closing_github_metric_date() -> str:
    """关榜轮目标日期：调度时区昨日（供次日 00:3x 关榜 job 使用）。"""
    return (_local_now().date() - timedelta(days=1)).isoformat()


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _merge_channels(existing: str, new_channel: str) -> str:
    parts = [part.strip() for part in (existing or "").split(",") if part.strip()]
    if new_channel not in parts:
        parts.append(new_channel)
    return ",".join(parts)


def _normalize_against_reference(raw: float, reference: float) -> float:
    """Map a raw signal to 0..100 against a stable business reference.

    Fixed references keep scores comparable across days and avoid assigning a
    near-100 score merely because a modest value happens to be in today's P95.
    """

    if raw <= 0 or reference <= 0:
        return 0.0
    return round(min(raw / reference, 1.0) * 100.0, 4)


def _growth_acceleration_curve(daily_growth: float, baseline_7d: float) -> float:
    """Map growth momentum to a continuous 0..100 score in log-ratio space."""

    if daily_growth <= 0:
        return 0.0
    ratio = (daily_growth + 1.0) / (max(baseline_7d, 0.0) + 1.0)
    if ratio <= _ACCELERATION_RATIO_ANCHORS[0][0]:
        return _ACCELERATION_RATIO_ANCHORS[0][1]
    if ratio >= _ACCELERATION_RATIO_ANCHORS[-1][0]:
        return _ACCELERATION_RATIO_ANCHORS[-1][1]

    for (lower_ratio, lower_score), (upper_ratio, upper_score) in zip(
        _ACCELERATION_RATIO_ANCHORS,
        _ACCELERATION_RATIO_ANCHORS[1:],
    ):
        if ratio <= upper_ratio:
            position = math.log(ratio / lower_ratio) / math.log(
                upper_ratio / lower_ratio
            )
            return lower_score + position * (upper_score - lower_score)
    return _ACCELERATION_RATIO_ANCHORS[-1][1]


def _maintenance_score(metric_date: str, pushed_at: Any) -> float:
    pushed_date = _parse_date(pushed_at)
    current_date = _parse_date(metric_date)
    if not pushed_date or not current_date:
        return 0.0
    days_since_push = max((current_date - pushed_date).days, 0)
    return round(100.0 / (1.0 + days_since_push / 14.0), 4)


def _candidate_payload(repo: Dict[str, Any], *, existing: Dict[str, Any] | None, captured_at: str) -> Dict[str, Any]:
    topics = repo.get("topics") or repo.get("tags") or []
    return {
        "repo_id": repo.get("repo_id") or (existing or {}).get("repo_id") or repo.get("full_name"),
        "full_name": repo.get("full_name") or (existing or {}).get("full_name") or repo.get("title") or "",
        "title": repo.get("title") or repo.get("full_name") or (existing or {}).get("title") or "",
        "url": repo.get("url") or (existing or {}).get("url") or "",
        "description": repo.get("description") or repo.get("summary") or (existing or {}).get("description") or "",
        "language": repo.get("language") or (existing or {}).get("language") or "",
        "topics_json": json.dumps(topics, ensure_ascii=False),
        "created_at": repo.get("created_at") or (existing or {}).get("created_at") or "",
        "pushed_at": repo.get("pushed_at") or (existing or {}).get("pushed_at") or "",
        "stars": int(repo.get("stars") or 0),
        "forks": int(repo.get("forks") or 0),
        "watchers": int(repo.get("watchers") or 0),
        "community_metrics_complete": bool(repo.get("community_metrics_complete")),
        "source_channels": _merge_channels(str((existing or {}).get("source_channels") or ""), "daily_metrics"),
        "last_snapshot_at": captured_at,
    }


def _snapshot_payload(repo: Dict[str, Any], *, metric_date: str, captured_at: str) -> Dict[str, Any]:
    return {
        "repo_id": repo.get("repo_id") or repo.get("full_name"),
        "full_name": repo.get("full_name") or "",
        "snapshot_date": metric_date,
        "captured_at": captured_at,
        "stars": int(repo.get("stars") or 0),
        "forks": int(repo.get("forks") or 0),
        "watchers": int(repo.get("watchers") or 0),
        "community_metrics_complete": (
            1 if repo.get("community_metrics_complete") else 0
        ),
        "open_issues": int(repo.get("open_issues") or 0),
        "repo_created_at": repo.get("created_at") or "",
        "repo_pushed_at": repo.get("pushed_at") or "",
    }


def refresh_github_project_metric_snapshots(
    *,
    min_stars: int = DEFAULT_MIN_STARS,
    limit: int = 0,
    metric_date: str | date | None = None,
    dry_run: bool = False,
    closing: bool = False,
    _local_date: date | None = None,
    _local_now: datetime | None = None,
    db: GitHubProjectIngestionRepository,
) -> Dict[str, Any]:
    """Refresh today's lightweight GitHub metrics and write raw snapshots.

    closing=True（关榜轮）时改用关榜日期解析：允许在次日 00:00–01:00
    窗口内把本轮观测写入昨日切片，收齐日界尾巴增长。
    """

    if closing:
        local_now = _local_now or _local_now()
        snapshot_date = _closing_metric_date(metric_date, local_now=local_now)
    else:
        snapshot_date = _live_metric_date(metric_date, local_today=_local_date)
    captured_at = _utcnow()
    targets = db.list_github_project_metric_targets(min_stars=min_stars, limit=limit)
    full_names = [str(item.get("full_name") or "").strip() for item in targets if item.get("full_name")]
    if dry_run:
        return {
            "status": "dry_run",
            "metric_date": snapshot_date,
            "targets": len(full_names),
            "snapshots": 0,
            "updated_candidates": 0,
        }

    outcomes = fetch_github_repo_metrics_batch(full_names)
    existing_by_name = {str(item.get("full_name") or "").lower(): item for item in targets}
    updated_candidates = 0
    snapshots = 0
    fetched = 0
    skipped = 0
    not_found_observations = 0
    newly_not_found = 0
    recovered = 0
    unknown = 0
    pending: List[Dict[str, Any]] = []
    pending_recovered = 0

    for outcome in outcomes:
        full_name = str(outcome.full_name or "").strip()
        if outcome.status == "not_found":
            skipped += 1
            not_found_observations += 1
            try:
                if db.record_github_repo_not_found(full_name, checked_at=captured_at):
                    newly_not_found += 1
            except Exception as exc:  # noqa: BLE001 - keep daily refresh moving
                logger.warning("[GitHubProjectMetrics] 仓库不可用状态写入失败 repo=%s error=%s", full_name, exc, exc_info=True)
            continue
        if outcome.status != "succeeded" or not outcome.metrics:
            skipped += 1
            unknown += 1
            continue

        repo = outcome.metrics
        fetched += 1
        full_name = str(repo.get("full_name") or full_name).strip()
        if not full_name:
            skipped += 1
            continue
        existing = existing_by_name.get(outcome.full_name.lower())
        pending_recovered += int((existing or {}).get("availability_status") == "not_found")
        pending.append(
            {
                "candidate": _candidate_payload(repo, existing=existing, captured_at=captured_at),
                "available_full_name": outcome.full_name,
                "snapshot": _snapshot_payload(repo, metric_date=snapshot_date, captured_at=captured_at),
            }
        )

    if pending:
        try:
            written = db.upsert_github_repo_metric_observations(pending, checked_at=captured_at)
        except Exception as exc:  # noqa: BLE001 - keep daily refresh moving
            skipped += len(pending)
            logger.warning("[GitHubProjectMetrics] 批量快照写入失败（整批回滚） count=%d error=%s", len(pending), exc, exc_info=True)
        else:
            updated_candidates += written
            snapshots += written
            recovered += pending_recovered

    skipped += max(0, len(full_names) - len(outcomes))
    result = {
        "status": "success",
        "metric_date": snapshot_date,
        "targets": len(full_names),
        "fetched": fetched,
        "updated_candidates": updated_candidates,
        "snapshots": snapshots,
        "skipped": skipped,
        "not_found_observations": not_found_observations,
        "newly_not_found": newly_not_found,
        "recovered": recovered,
        "unknown": unknown,
    }
    logger.info("[GitHubProjectMetrics] 每日指标快照刷新完成：%s", result)
    return result


def compute_github_daily_metrics(
    *,
    metric_date: str | date | None = None,
    min_stars: int = DEFAULT_MIN_STARS,
    repo_ids: List[str] | None = None,
    db: GitHubProjectIngestionRepository,
) -> Dict[str, Any]:
    """Compute exact day-over-day growth and scale-adjusted hot scores."""

    metric_date_str = _date_str(metric_date)
    current_date = date.fromisoformat(metric_date_str)
    previous_date = (current_date - timedelta(days=1)).isoformat()
    baseline_start_date = (current_date - timedelta(days=7)).isoformat()

    rows = db.get_github_daily_metric_inputs(
        metric_date=metric_date_str,
        previous_date=previous_date,
        baseline_start_date=baseline_start_date,
        min_stars=min_stars,
        repo_ids=repo_ids,
    )

    staged: List[Dict[str, Any]] = []

    for row in rows:
        # 基线快照由 SQL 在窗口内向前回溯（latest ≤ previous_date 且 ≥ baseline_start）：
        # 采集断供日没有精确昨日快照时，用最近一次快照兜底，避免整日 zero-growth。
        previous_snapshot_date = str(row.get("previous_snapshot_date") or "")
        has_previous = False
        baseline_gap_days = 1
        if previous_snapshot_date:
            try:
                baseline_gap_days = max(
                    (current_date - date.fromisoformat(previous_snapshot_date)).days,
                    1,
                )
                has_previous = True
            except ValueError:
                logger.warning(
                    "[GitHubProjectMetrics] 仓库 %s 基线快照日期非法（%r），按无基线处理。",
                    row.get("repo_id"),
                    previous_snapshot_date,
                )
        exact_baseline = previous_snapshot_date == previous_date
        trending_growth_value = row.get("trending_daily_star_growth")
        has_trending_growth = trending_growth_value is not None
        stars = int(row.get("stars") or 0)
        forks = int(row.get("forks") or 0)
        watchers = int(row.get("watchers") or 0)
        previous_stars = int(row.get("previous_stars") or 0)
        has_complete_community_pair = (
            has_previous
            and row.get("community_metrics_complete") == 1
            and row.get("previous_community_metrics_complete") == 1
        )
        if has_previous:
            # 断供跨天的基线按间隔天数归一化为日增速率，防止 2 天增量被读成
            # 单日暴涨；source 标记 snapshot_delta_gap 以便与精确日增区分
            # （且不进入 baseline_7d 日均样本）。
            growth_source = "snapshot_delta" if exact_baseline else "snapshot_delta_gap"
            growth_observed_at = None
            daily_growth = max(stars - previous_stars, 0) // baseline_gap_days
            daily_fork_growth = (
                max(forks - int(row.get("previous_forks") or 0), 0) // baseline_gap_days
                if has_complete_community_pair
                else 0
            )
            daily_watcher_growth = (
                max(watchers - int(row.get("previous_watchers") or 0), 0) // baseline_gap_days
                if has_complete_community_pair
                else 0
            )
            scale_base_stars = max(previous_stars, 100)
        elif has_trending_growth:
            growth_source = "github_trending_daily"
            growth_observed_at = row.get("trending_daily_observed_at")
            daily_growth = max(int(trending_growth_value or 0), 0)
            daily_fork_growth = 0
            daily_watcher_growth = 0
            scale_base_stars = max(stars - daily_growth, 100)
        else:
            growth_source = "unavailable"
            growth_observed_at = None
            daily_growth = 0
            daily_fork_growth = 0
            daily_watcher_growth = 0
            scale_base_stars = max(stars, 100)
        available = growth_source != "unavailable"
        baseline_7d = float(row.get("baseline_7d") or 0.0)
        baseline_sample_count = int(row.get("baseline_sample_count") or 0)

        if available:
            scale_raw = math.log1p(daily_growth / math.sqrt(scale_base_stars))
            acceleration_curve_score = _growth_acceleration_curve(
                daily_growth,
                baseline_7d,
            )
            absolute_raw = math.log1p(daily_growth)
            community_raw = (
                0.6 * math.log1p(daily_fork_growth)
                + 0.4 * math.log1p(daily_watcher_growth)
                if has_complete_community_pair
                else 0.0
            )
        else:
            scale_raw = absolute_raw = community_raw = 0.0
            acceleration_curve_score = 0.0
        staged.append(
            {
                "repo_id": row.get("repo_id"),
                "metric_date": metric_date_str,
                "stars": stars,
                "forks": forks,
                "watchers": watchers,
                "open_issues": int(row.get("open_issues") or 0),
                "previous_snapshot_date": previous_snapshot_date if has_previous else None,
                "previous_stars": previous_stars if has_previous else 0,
                "daily_star_growth": daily_growth,
                "daily_fork_growth": daily_fork_growth,
                "daily_watcher_growth": daily_watcher_growth,
                "daily_growth_available": available,
                "daily_growth_source": growth_source,
                "daily_growth_observed_at": growth_observed_at,
                "maintenance_activity_score": _maintenance_score(metric_date_str, row.get("repo_pushed_at")),
                "_scale_raw": scale_raw,
                "_acceleration_curve_score": acceleration_curve_score,
                "_acceleration_confidence": min(
                    max(baseline_sample_count, 0)
                    / _FULL_ACCELERATION_CONFIDENCE_SAMPLES,
                    1.0,
                ),
                "_absolute_raw": absolute_raw,
                "_community_raw": community_raw,
            }
        )

    metrics: List[Dict[str, Any]] = []
    available_count = 0
    exact_count = 0
    gap_fallback_count = 0
    trending_fallback_count = 0
    positive_growth_count = 0
    for item in staged:
        available = bool(item["daily_growth_available"])
        if available:
            available_count += 1
        if item.get("daily_growth_source") == "snapshot_delta":
            exact_count += 1
        elif item.get("daily_growth_source") == "snapshot_delta_gap":
            gap_fallback_count += 1
        elif item.get("daily_growth_source") == "github_trending_daily":
            trending_fallback_count += 1
        if int(item["daily_star_growth"] or 0) > 0:
            positive_growth_count += 1
        scale_score = _normalize_against_reference(float(item.pop("_scale_raw")), _SCALE_GROWTH_REFERENCE) if available else 0.0
        acceleration_score = (
            round(
                float(item.pop("_acceleration_curve_score"))
                * float(item.pop("_acceleration_confidence")),
                4,
            )
            if available
            else 0.0
        )
        absolute_score = _normalize_against_reference(float(item.pop("_absolute_raw")), _ABSOLUTE_GROWTH_REFERENCE) if available else 0.0
        community_score = _normalize_against_reference(float(item.pop("_community_raw")), _COMMUNITY_REFERENCE) if available else 0.0
        maintenance_score = float(item.get("maintenance_activity_score") or 0.0) if available else 0.0
        hot_score = 0.0
        if available:
            hot_score = round(
                0.55 * scale_score
                + 0.20 * acceleration_score
                + 0.10 * absolute_score
                + 0.10 * maintenance_score
                + 0.05 * community_score,
                4,
            )
        item.update(
            {
                "scale_corrected_growth_score": scale_score,
                "growth_acceleration_score": acceleration_score,
                "absolute_growth_score": absolute_score,
                "maintenance_activity_score": maintenance_score,
                "community_engagement_score": community_score,
                "hot_score": hot_score,
                "score_version": DEFAULT_SCORE_VERSION,
                "updated_at": _utcnow(),
            }
        )
        metrics.append(item)

    affected = db.upsert_github_daily_metrics(metrics)
    result = {
        "status": "success",
        "metric_date": metric_date_str,
        "previous_date": previous_date,
        "rows": len(metrics),
        "available": available_count,
        "exact": exact_count,
        "gap_fallback": gap_fallback_count,
        "trending_fallback": trending_fallback_count,
        "positive_growth": positive_growth_count,
        "targeted": bool(repo_ids),
        "affected": affected,
        "score_version": DEFAULT_SCORE_VERSION,
    }
    logger.info("[GitHubProjectMetrics] 每日热度指标计算完成：%s", result)
    return result


def refresh_and_compute_github_project_metrics(
    *,
    min_stars: int = DEFAULT_MIN_STARS,
    limit: int = 0,
    metric_date: str | date | None = None,
    dry_run: bool = False,
    closing: bool = False,
    _local_now: datetime | None = None,
    db: GitHubProjectIngestionRepository,
) -> Dict[str, Any]:
    if closing:
        local_now = _local_now or _local_now()
        resolved_date = _closing_metric_date(metric_date, local_now=local_now)
        refresh_result = refresh_github_project_metric_snapshots(
            min_stars=min_stars,
            limit=limit,
            metric_date=resolved_date,
            dry_run=dry_run,
            closing=True,
            _local_now=local_now,
            db=db,
        )
    else:
        local_today = _local_today()
        resolved_date = _live_metric_date(metric_date, local_today=local_today)
        refresh_result = refresh_github_project_metric_snapshots(
            min_stars=min_stars,
            limit=limit,
            metric_date=resolved_date,
            dry_run=dry_run,
            _local_date=local_today,
            db=db,
        )
    metrics_result = None
    if not dry_run:
        metrics_result = compute_github_daily_metrics(
            metric_date=resolved_date,
            min_stars=min_stars,
            db=db,
        )
    return {
        "status": "success" if not dry_run else "dry_run",
        "metric_date": resolved_date,
        "refresh": refresh_result,
        "metrics": metrics_result,
    }
