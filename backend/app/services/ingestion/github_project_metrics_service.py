from __future__ import annotations

"""Daily GitHub project metric snapshots and hot-score computation."""

import json
import logging
import threading
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from backend.app.core.config import settings
from backend.app.domain.github_heat import (
    SCORE_VERSION,
    HeatInputs,
    days_since,
    score_heat,
    snapshot_velocity,
    suspicion_multiplier,
)
from backend.app.repositories.project_write_repository import (
    GitHubProjectIngestionRepository,
)
from backend.app.services.ingestion.source_github import fetch_github_repo_metrics_batch

logger = logging.getLogger(__name__)

# 两小时指标刷新与新仓快车道可能并行（见 scheduler.GitHubFastLaneShare）：
# 抓取各自进行，写库与算分串行。避免两个批量事务互锁回滚整轮写入，也避免
# 读到旧快照的整轮算分覆盖快车道刚写入的新指标——算分在锁内读输入、写结果，
# 后跑的一方总能读到双方合并后的快照（快照 upsert 按 GREATEST 合并）。
_METRIC_WRITE_LOCK = threading.RLock()

DEFAULT_MIN_STARS = 500
_FULL_BASELINE_SAMPLES = 3

# 反作弊信号阈值：加和封顶 1.0，≥0.5 才降权（见 github_heat）——单仓信号需两个
# 及以上叠加，跨账号的 coordinated_creation 单独即可；跨渠道佐证命中时分数清零、
# signals 仍留痕。
_SUSPICION_MIN_GROWTH = 100  # 日增低于此不参与判定（小波动噪声太大）
_FORK_FOLLOW_RATIO = 0.01  # fork 跟随率阈值：刷量仓只涨星不涨 fork
_PULSE_BASELINE_EPS = 1.0  # 7 日基线 ≈ 0 → 从零脉冲
_NEW_REPO_DAYS = 30
_NEW_REPO_MIN_GROWTH = 200
_COORDINATED_WINDOW = timedelta(minutes=5)
_COORDINATED_MIN_OWNERS = 3
_SIGNAL_WEIGHTS = {
    "low_fork_follow": 0.4,
    "spike_from_zero_baseline": 0.3,
    "new_repo_surge": 0.2,
    # 跨账号证据本身足够强：单独即达降权阈值。
    "coordinated_creation": 0.6,
}


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


def corroboration_window(metric_date: str | date) -> tuple[str, str]:
    """反作弊佐证查询窗口：metric_date 前后各扩一天。

    metric_date 是调度时区（Asia/Shanghai）自然日，而 documents.created_at
    是 UTC、部分源 published_date 用 PT——存在性佐证宁宽勿漏，前后各扩
    一天吸收日界错位。
    """
    current = date.fromisoformat(_date_str(metric_date))
    return (current - timedelta(days=1)).isoformat(), (current + timedelta(days=1)).isoformat()


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


def _growth_suspicion(
    *,
    metric_date: str,
    daily_star_growth: float,
    daily_fork_growth: float,
    has_complete_community_pair: bool,
    baseline_7d: float,
    baseline_sample_count: int,
    repo_created_at: Any,
    corroborated: bool,
    coordinated_creation: bool = False,
) -> tuple[float, list[str], bool]:
    """反作弊一二层打标：行为比率信号加和（封顶 1.0），佐证命中清零。

    信号语义：
      low_fork_follow         刷量账号只点星，fork 跟随率趋近 0；
                              community pair 不完整时跳过（unknown ≠ 0）。
      spike_from_zero_baseline 7 日基线 ≈ 0 的单日脉冲（买量典型形态）；
                              基线样本不足 3 天时跳过（无历史 ≠ 零基线）。
      new_repo_surge          新仓单日巨量增长且（通常）无外部出处。
      coordinated_creation    ≥3 个不同账号同一 5 分钟内建仓且同日暴涨
                              （批量注册的诱饵仓，见 _coordinated_creation_repo_ids）。
    佐证（corroborated=True）不清除 signals——留痕供误报复核，只清零分数。
    """

    signals: list[str] = []
    if daily_star_growth >= _SUSPICION_MIN_GROWTH:
        if (
            has_complete_community_pair
            and daily_fork_growth / daily_star_growth < _FORK_FOLLOW_RATIO
        ):
            signals.append("low_fork_follow")
        if (
            baseline_sample_count >= _FULL_BASELINE_SAMPLES
            and baseline_7d < _PULSE_BASELINE_EPS
        ):
            signals.append("spike_from_zero_baseline")
        created_date = _parse_date(repo_created_at)
        current_date = _parse_date(metric_date)
        if (
            created_date
            and current_date
            and 0 <= (current_date - created_date).days < _NEW_REPO_DAYS
            and daily_star_growth >= _NEW_REPO_MIN_GROWTH
        ):
            signals.append("new_repo_surge")
        if coordinated_creation:
            signals.append("coordinated_creation")
    score = min(sum(_SIGNAL_WEIGHTS[name] for name in signals), 1.0)
    if corroborated:
        return 0.0, signals, True
    return round(score, 4), signals, False


def _candidate_payload(repo: Dict[str, Any], *, existing: Dict[str, Any] | None, captured_at: str) -> Dict[str, Any]:
    topics = repo.get("topics") or repo.get("tags") or []
    return {
        "repo_id": repo.get("repo_id") or (existing or {}).get("repo_id") or repo.get("full_name"),
        "full_name": repo.get("full_name") or (existing or {}).get("full_name") or repo.get("title") or "",
        "title": repo.get("title") or repo.get("full_name") or (existing or {}).get("title") or "",
        "url": repo.get("url") or (existing or {}).get("url") or "",
        "description": repo.get("description") or repo.get("summary") or (existing or {}).get("description") or "",
        "language": repo.get("language") or (existing or {}).get("language") or "",
        "license_spdx_id": repo.get("license_spdx_id") or (existing or {}).get("license_spdx_id") or "",
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


def record_github_metric_outcomes(
    *,
    targets: List[Dict[str, Any]],
    outcomes: List[Any],
    snapshot_date: str,
    captured_at: str,
    db: GitHubProjectIngestionRepository,
) -> Dict[str, Any]:
    with _METRIC_WRITE_LOCK:
        return _record_github_metric_outcomes(
            targets=targets,
            outcomes=outcomes,
            snapshot_date=snapshot_date,
            captured_at=captured_at,
            db=db,
        )


def _record_github_metric_outcomes(
    *,
    targets: List[Dict[str, Any]],
    outcomes: List[Any],
    snapshot_date: str,
    captured_at: str,
    db: GitHubProjectIngestionRepository,
) -> Dict[str, Any]:
    """把一批指标抓取结果事务化落库并返回分类计数。

    日刷与存量身份巡检脚本共用本写入路径：调用方负责目标选取与抓取，
    本函数负责 404 累计、改名识别（renamed_from）、候选 upsert 与快照插入。
    改名识别：跟随 301 后 API 返回的权威 full_name 与请求名不一致（区分
    大小写）时，observation 携带 renamed_from=旧请求名，由仓储层把旧名
    候选行归一/合并到新名。
    快照与候选的时间戳取各 outcome 的 observed_at（该批响应到达时刻），
    缺失时回退 captured_at（开轮时刻）；可用性检查时刻仍按轮记 captured_at。
    """
    existing_by_name = {str(item.get("full_name") or "").lower(): item for item in targets}
    updated_candidates = 0
    snapshots = 0
    fetched = 0
    skipped = 0
    not_found_observations = 0
    newly_not_found = 0
    recovered = 0
    unknown = 0
    renamed = 0
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
        api_full_name = str(repo.get("full_name") or "").strip()
        full_name = api_full_name or full_name
        if not full_name:
            skipped += 1
            continue
        renamed_from = ""
        if api_full_name and api_full_name != str(outcome.full_name or "").strip():
            renamed_from = str(outcome.full_name or "").strip()
            renamed += 1
        existing = existing_by_name.get(str(outcome.full_name or "").lower())
        pending_recovered += int((existing or {}).get("availability_status") == "not_found")
        observed_at = str(getattr(outcome, "observed_at", "") or "") or captured_at
        pending.append(
            {
                "candidate": _candidate_payload(repo, existing=existing, captured_at=observed_at),
                "available_full_name": outcome.full_name,
                "renamed_from": renamed_from,
                "snapshot": _snapshot_payload(repo, metric_date=snapshot_date, captured_at=observed_at),
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
    return {
        "fetched": fetched,
        "updated_candidates": updated_candidates,
        "snapshots": snapshots,
        "skipped": skipped,
        "not_found_observations": not_found_observations,
        "newly_not_found": newly_not_found,
        "recovered": recovered,
        "unknown": unknown,
        "renamed": renamed,
    }


def refresh_github_project_metric_snapshots(
    *,
    min_stars: int = DEFAULT_MIN_STARS,
    limit: int = 0,
    metric_date: str | date | None = None,
    dry_run: bool = False,
    closing: bool = False,
    _local_date: date | None = None,
    _now: datetime | None = None,
    db: GitHubProjectIngestionRepository,
) -> Dict[str, Any]:
    """Refresh today's lightweight GitHub metrics and write raw snapshots.

    closing=True（关榜轮）时改用关榜日期解析：允许在次日 00:00–01:00
    窗口内把本轮观测写入昨日切片，收齐日界尾巴增长。
    """

    if closing:
        local_now = _now or _local_now()
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
    counts = record_github_metric_outcomes(
        targets=targets,
        outcomes=outcomes,
        snapshot_date=snapshot_date,
        captured_at=captured_at,
        db=db,
    )
    counts["skipped"] += max(0, len(full_names) - len(outcomes))
    result = {
        "status": "success",
        "metric_date": snapshot_date,
        "targets": len(full_names),
        **counts,
    }
    logger.info("[GitHubProjectMetrics] 每日指标快照刷新完成：%s", result)
    return result


def _observed_growth(row: Dict[str, Any], *, current_date: date, previous_date: str) -> Dict[str, Any]:
    """Observed day-over-day deltas; the daily metric contract, independent of heat."""

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
    trending_growth_value = row.get("trending_daily_star_growth")
    stars = int(row.get("stars") or 0)
    forks = int(row.get("forks") or 0)
    watchers = int(row.get("watchers") or 0)
    previous_stars = int(row.get("previous_stars") or 0)
    has_complete_community_pair = (
        has_previous
        and row.get("community_metrics_complete") == 1
        and row.get("previous_community_metrics_complete") == 1
    )
    growth_observed_at = None
    daily_fork_growth = daily_watcher_growth = 0
    if has_previous:
        # 断供跨天的基线按间隔天数归一化为日增速率，防止 2 天增量被读成
        # 单日暴涨；source 标记 snapshot_delta_gap 以便与精确日增区分
        # （且不进入 baseline_7d 日均样本）。
        growth_source = "snapshot_delta" if previous_snapshot_date == previous_date else "snapshot_delta_gap"
        daily_growth = max(stars - previous_stars, 0) // baseline_gap_days
        if has_complete_community_pair:
            daily_fork_growth = max(forks - int(row.get("previous_forks") or 0), 0) // baseline_gap_days
            daily_watcher_growth = max(watchers - int(row.get("previous_watchers") or 0), 0) // baseline_gap_days
        base_stars = previous_stars
    elif trending_growth_value is not None:
        growth_source = "github_trending_daily"
        growth_observed_at = row.get("trending_daily_observed_at")
        daily_growth = max(int(trending_growth_value or 0), 0)
        base_stars = stars - daily_growth
    else:
        growth_source = "unavailable"
        daily_growth = 0
        base_stars = stars
    return {
        "stars": stars,
        "forks": forks,
        "watchers": watchers,
        "open_issues": int(row.get("open_issues") or 0),
        "previous_snapshot_date": previous_snapshot_date if has_previous else None,
        "previous_stars": previous_stars if has_previous else 0,
        "daily_star_growth": daily_growth,
        "daily_fork_growth": daily_fork_growth,
        "daily_watcher_growth": daily_watcher_growth,
        "daily_growth_available": growth_source != "unavailable",
        "daily_growth_source": growth_source,
        "daily_growth_observed_at": growth_observed_at,
        "_base_stars": base_stars,
        "_has_complete_community_pair": has_complete_community_pair,
    }


def _coordinated_creation_repo_ids(candidates: List[tuple[str, str, Any]]) -> set[str]:
    """同日暴涨的仓库里，≥3 个不同账号在同一 5 分钟窗口内建仓 → 批量注册的诱饵仓。

    candidates: (repo_id, full_name, created_at)。只认精确到分钟的建仓时间；
    跨仓信号只在本次计算的行里成簇，定向重算看不到窗口外的同伙。
    """

    stamped: List[tuple[datetime, str, str]] = []
    for repo_id, full_name, created_at in candidates:
        text = str(created_at or "")
        if "/" not in full_name or len(text) < 16 or text[10] != "T":
            continue
        try:
            created = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        stamped.append((created, full_name.split("/", 1)[0].lower(), repo_id))
    stamped.sort()
    flagged: set[str] = set()
    start = 0
    for end in range(len(stamped)):
        while stamped[end][0] - stamped[start][0] > _COORDINATED_WINDOW:
            start += 1
        window = stamped[start : end + 1]
        if len({owner for _, owner, _ in window}) >= _COORDINATED_MIN_OWNERS:
            flagged.update(repo_id for _, _, repo_id in window)
    return flagged


def compute_github_daily_metrics(
    *,
    metric_date: str | date | None = None,
    min_stars: int = DEFAULT_MIN_STARS,
    repo_ids: List[str] | None = None,
    corroborated_repo_ids: set[str] | None = None,
    db: GitHubProjectIngestionRepository,
) -> Dict[str, Any]:
    """Compute exact day-over-day growth and scale-adjusted hot scores.

    corroborated_repo_ids: 当日在其他渠道（HN/news/dailyhot/X）有曝光的
    repo_id 集合，用于反作弊佐证清零；None 表示跳过佐证（向后兼容）。
    """
    with _METRIC_WRITE_LOCK:
        return _compute_github_daily_metrics(
            metric_date=metric_date,
            min_stars=min_stars,
            repo_ids=repo_ids,
            corroborated_repo_ids=corroborated_repo_ids,
            db=db,
        )


def _compute_github_daily_metrics(
    *,
    metric_date: str | date | None,
    min_stars: int,
    repo_ids: List[str] | None,
    corroborated_repo_ids: set[str] | None,
    db: GitHubProjectIngestionRepository,
) -> Dict[str, Any]:

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
    observed = [
        (row, _observed_growth(row, current_date=current_date, previous_date=previous_date))
        for row in rows
    ]
    coordinated = _coordinated_creation_repo_ids(
        [
            (
                str(row.get("repo_id") or ""),
                str(row.get("full_name") or ""),
                # 快照只存建仓日期；候选池保留 API 原始时间戳。
                row.get("candidate_created_at") or row.get("repo_created_at"),
            )
            for row, item in observed
            if item["daily_star_growth"] >= _SUSPICION_MIN_GROWTH
        ]
    )

    metrics: List[Dict[str, Any]] = []
    snapshot_velocity_count = 0
    observed_velocity_count = 0
    for row, item in observed:
        daily_growth = item["daily_star_growth"]
        has_complete_community_pair = item.pop("_has_complete_community_pair")
        base_stars = item.pop("_base_stars")
        baseline_7d = float(row.get("baseline_7d") or 0.0)
        baseline_sample_count = int(row.get("baseline_sample_count") or 0)
        suspicion_score, suspicion_signals, corroborated = (
            _growth_suspicion(
                metric_date=metric_date_str,
                daily_star_growth=float(daily_growth),
                daily_fork_growth=float(item["daily_fork_growth"]),
                has_complete_community_pair=has_complete_community_pair,
                baseline_7d=baseline_7d,
                baseline_sample_count=baseline_sample_count,
                repo_created_at=row.get("repo_created_at"),
                # 同一批账号前 7 天已成簇的，后续日增不再凑满 3 个也继续标记。
                coordinated_creation=(
                    str(row.get("repo_id") or "") in coordinated
                    or bool(row.get("prior_coordinated_creation"))
                ),
                corroborated=(
                    corroborated_repo_ids is not None
                    and str(row.get("repo_id") or "").lower() in corroborated_repo_ids
                ),
            )
            if item["daily_growth_available"]
            else (0.0, [], False)
        )
        if item["daily_growth_available"]:
            # 同一口径打分：快照时间序列可用时按实际间隔小时折算速率，否则用
            # 观测日增（含 Trending 冷启动）。缺失输入是未知而非 0。
            inputs = snapshot_velocity(row.get("heat_snapshot_history") or [], metric_date_str)
            if inputs is None:
                observed_velocity_count += 1
                inputs = HeatInputs(
                    star_velocity=float(daily_growth),
                    base_stars=float(base_stars),
                    baseline_velocity=baseline_7d if baseline_sample_count > 0 else None,
                    baseline_confidence=min(baseline_sample_count / _FULL_BASELINE_SAMPLES, 1.0),
                    fork_velocity=float(item["daily_fork_growth"]) if has_complete_community_pair else None,
                    watcher_velocity=float(item["daily_watcher_growth"]) if has_complete_community_pair else None,
                    days_since_push=days_since(metric_date_str, row.get("repo_pushed_at")),
                )
            else:
                snapshot_velocity_count += 1
            if daily_growth <= 0:
                # 观测日增为 0 的仓库不应凭前一区间速率或次要信号获得热度。
                inputs = replace(inputs, star_velocity=0.0)
            scores = score_heat(inputs, suspicion=suspicion_score)
        else:
            scores = score_heat(HeatInputs(star_velocity=0.0, base_stars=float(base_stars)))
            scores.update(maintenance_activity_score=0.0, community_engagement_score=0.0)
        metrics.append(
            {
                "repo_id": row.get("repo_id"),
                "metric_date": metric_date_str,
                **item,
                **scores,
                "growth_suspicion_score": suspicion_score,
                "growth_suspicion_signals": json.dumps(suspicion_signals, ensure_ascii=False),
                "growth_corroborated": corroborated,
                "updated_at": _utcnow(),
            }
        )

    affected = db.upsert_github_daily_metrics(metrics)
    sources = [item["daily_growth_source"] for item in metrics]
    result = {
        "status": "success",
        "metric_date": metric_date_str,
        "previous_date": previous_date,
        "rows": len(metrics),
        "available": sum(1 for source in sources if source != "unavailable"),
        "exact": sources.count("snapshot_delta"),
        "gap_fallback": sources.count("snapshot_delta_gap"),
        "trending_fallback": sources.count("github_trending_daily"),
        "positive_growth": sum(1 for item in metrics if item["daily_star_growth"] > 0),
        "suspicious": sum(1 for item in metrics if item["growth_suspicion_score"] > 0),
        "demoted": sum(
            1
            for item in metrics
            if item["daily_star_growth"] > 0 and suspicion_multiplier(item["growth_suspicion_score"]) < 1
        ),
        "corroborated": sum(1 for item in metrics if item["growth_corroborated"]),
        "targeted": bool(repo_ids),
        "affected": affected,
        "score_version": SCORE_VERSION,
        "snapshot_velocity": snapshot_velocity_count,
        "observed_velocity": observed_velocity_count,
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
    corroborated_repo_ids: set[str] | None = None,
    _now: datetime | None = None,
    db: GitHubProjectIngestionRepository,
) -> Dict[str, Any]:
    if closing:
        local_now = _now or _local_now()
        resolved_date = _closing_metric_date(metric_date, local_now=local_now)
        refresh_result = refresh_github_project_metric_snapshots(
            min_stars=min_stars,
            limit=limit,
            metric_date=resolved_date,
            dry_run=dry_run,
            closing=True,
            _now=local_now,
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
            corroborated_repo_ids=corroborated_repo_ids,
            db=db,
        )
    return {
        "status": "success" if not dry_run else "dry_run",
        "metric_date": resolved_date,
        "refresh": refresh_result,
        "metrics": metrics_result,
    }


def refresh_and_compute_github_target_metrics(
    *,
    targets: List[Dict[str, Any]],
    min_stars: int = DEFAULT_MIN_STARS,
    corroborated_repo_ids: set[str] | None = None,
    db: GitHubProjectIngestionRepository,
) -> Dict[str, Any]:
    """为显式给定的一批仓库刷新当天快照，并只重算这批仓库的当天指标。

    新仓快车道用：targets 是刚爬到的候选载荷（repo_id/full_name/
    source_channels 等），与日刷共用 record_github_metric_outcomes 写入
    路径和 compute_github_daily_metrics 口径，只是范围收窄到子集。
    targets 为空时直接跳过——compute 的 repo_ids 为空意味着全量重算，
    绝不能落到那条路径上。
    """
    snapshot_date = _live_metric_date(None, local_today=_local_today())
    full_names: List[str] = []
    repo_ids: List[str] = []
    seen: set[str] = set()
    for item in targets:
        full_name = str(item.get("full_name") or "").strip()
        if not full_name or full_name.lower() in seen:
            continue
        seen.add(full_name.lower())
        full_names.append(full_name)
        repo_ids.append(str(item.get("repo_id") or full_name).strip())
    if not full_names:
        return {
            "status": "skipped",
            "metric_date": snapshot_date,
            "refresh": {"targets": 0},
            "metrics": None,
        }

    captured_at = _utcnow()
    outcomes = fetch_github_repo_metrics_batch(full_names)
    counts = record_github_metric_outcomes(
        targets=targets,
        outcomes=outcomes,
        snapshot_date=snapshot_date,
        captured_at=captured_at,
        db=db,
    )
    counts["skipped"] += max(0, len(full_names) - len(outcomes))
    metrics_result = compute_github_daily_metrics(
        metric_date=snapshot_date,
        min_stars=min_stars,
        repo_ids=repo_ids,
        corroborated_repo_ids=corroborated_repo_ids,
        db=db,
    )
    return {
        "status": "success",
        "metric_date": snapshot_date,
        "refresh": {"targets": len(full_names), **counts},
        "metrics": metrics_result,
    }
