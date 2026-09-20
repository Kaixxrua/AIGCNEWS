from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Protocol

from backend.app.repositories.rank_snapshot_repository import RankSnapshotReader
from backend.app.services.dashboard.policy import (
    DEFAULT_SNAPSHOT_LOOKBACK_DAYS,
    SnapshotDateResolution,
    build_date_resolution,
    github_metric_to_doc,
    resolve_default_snapshot_date,
    resolve_snapshot_date,
    today_local,
)

SOURCE_PERIOD_CHANNELS: dict[str, dict[str, str]] = {
    "arxiv": {
        "daily": "huggingface_daily_html",
        "weekly": "huggingface_weekly_html",
        "monthly": "huggingface_monthly_html",
    },
    "github": {
        "daily": "github_trending_daily",
        "weekly": "github_trending_weekly",
        "monthly": "github_trending_monthly",
    },
    "news": {
        "daily": "techmeme_daily_rss",
        "weekly": "techmeme_daily_rss",
        "monthly": "techmeme_daily_rss",
    },
    "producthunt": {
        "daily": "producthunt_daily_html",
        "weekly": "producthunt_weekly_html",
        "monthly": "producthunt_monthly_html",
    },
    "hackernews": {
        "daily": "hn_daily_html",
        "weekly": "hn_weekly_html",
        "monthly": "hn_monthly_html",
    },
    # X 仅 daily：推文无周/月榜语义（采集器 supported_periods=["daily"]）
    "x": {
        "daily": "x_daily_watchlist",
    },
}

SAME_PERIOD_FALLBACKS: dict[str, dict[str, tuple[str, ...]]] = {
    "github": {
        "daily": ("github_hot_daily", "github_fallback"),
        "weekly": ("github_hot_weekly",),
        "monthly": ("github_hot_monthly",),
    }
}


class GitHubHotBoardReader(Protocol):
    """看板 github 榜的 v5 热度指标读取边界（由项目库目录仓储结构式满足）。"""

    def list_github_hot_for_date(
        self,
        *,
        metric_date: str,
        limit: int,
    ) -> list[dict[str, Any]]: ...

    def list_github_hot_dates(self, *, limit: int = 60) -> list[str]: ...


class DashboardQueryService:
    def __init__(
        self,
        rank_snapshots: RankSnapshotReader,
        github_hot: GitHubHotBoardReader | None = None,
    ) -> None:
        self._rank_snapshots = rank_snapshots
        # 看板 REST 路由注入项目库热度读取后，github 日榜改走 v5 指标
        # （今日暴涨口径）；未注入的调用方（MCP inbound 等）保持
        # rank_snapshots 的 trending 快照口径不变。
        self._github_hot = github_hot

    def resolve_display_snapshot_date(
        self,
        date_param: str | None,
        period: str = "daily",
        source_type: str | None = None,
    ) -> SnapshotDateResolution:
        """解析看板展示日期：显式 date 原样生效（诚实服务，不回溯）。

        默认视图（无 date）在 today 无快照时，按 source+period 口径向前
        回溯窗口内最近一个快照日期（包括未定稿快照）；结果始终带
        requested/resolved/stale 标记，回溯绝不静默。github 日榜注入 v5 读取后
        按指标日期回溯。
        """
        requested = resolve_snapshot_date(date_param)
        if date_param:
            return build_date_resolution(requested, requested)
        source = None if source_type in (None, "", "all") else source_type
        if source == "github" and period == "daily" and self._github_hot is not None:
            available = self._github_hot.list_github_hot_dates(
                limit=DEFAULT_SNAPSHOT_LOOKBACK_DAYS
            )
        else:
            available = self._rank_snapshots.get_snapshot_dates(
                DEFAULT_SNAPSHOT_LOOKBACK_DAYS, source, period
            )
        resolved = resolve_default_snapshot_date(available) or requested
        return build_date_resolution(requested, resolved)

    def get_docs_for_date(
        self,
        date_str: str,
        period: str,
        source_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        all_snapshot_docs: list[dict[str, Any]] = []

        if source_type and source_type != "all":
            if source_type == "github" and self._use_github_hot(period):
                return self._github_hot_docs(date_str, limit)
            channel = SOURCE_PERIOD_CHANNELS.get(source_type, {}).get(period)
            if channel:
                all_snapshot_docs.extend(
                    self._read(date_str, channel, source_type, limit)
                )
            if not all_snapshot_docs:
                self._append_first_fallback(
                    all_snapshot_docs, date_str, source_type, period, limit
                )
        else:
            for source, period_channels in SOURCE_PERIOD_CHANNELS.items():
                if source == "github" and self._use_github_hot(period):
                    all_snapshot_docs.extend(self._github_hot_docs(date_str, limit))
                    continue
                channel = period_channels.get(period)
                if not channel:
                    continue
                docs = self._read(date_str, channel, source, limit)
                if docs:
                    all_snapshot_docs.extend(docs)
                    continue
                self._append_first_fallback(
                    all_snapshot_docs, date_str, source, period, limit
                )

        if all_snapshot_docs and period == "daily":
            return self._apply_hackernews_daily_dedup(date_str, all_snapshot_docs)
        return all_snapshot_docs

    def _use_github_hot(self, period: str) -> bool:
        """github 日榜是否走 v5 热度指标（周/月榜无指标口径，仍走快照）。"""
        return period == "daily" and self._github_hot is not None

    def _github_hot_docs(self, date_str: str, limit: int) -> list[dict[str, Any]]:
        """项目库今日暴涨：按 hot_score(v5) 排序的正增长仓库，映射为看板 doc。

        指标缺失的日期返回空（诚实空榜），不回退 trending——两套口径
        混排会让名次含义漂移。
        """
        assert self._github_hot is not None  # 仅经 _use_github_hot 守门后调用
        rows = self._github_hot.list_github_hot_for_date(
            metric_date=date_str, limit=limit
        )
        return [
            github_metric_to_doc(row, rank=index + 1)
            for index, row in enumerate(rows)
        ]

    def _read(
        self,
        date_str: str,
        channel: str,
        source_type: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        return self._rank_snapshots.get_snapshot_documents(
            snapshot_date=date_str,
            source_channel=channel,
            source_type=source_type,
            limit=limit,
        )

    def _append_first_fallback(
        self,
        destination: list[dict[str, Any]],
        date_str: str,
        source_type: str,
        period: str,
        limit: int,
    ) -> None:
        fallbacks = SAME_PERIOD_FALLBACKS.get(source_type, {}).get(period, ())
        for fallback_channel in fallbacks:
            docs = self._read(date_str, fallback_channel, source_type, limit)
            if docs:
                destination.extend(docs)
                break

    def _apply_hackernews_daily_dedup(
        self, date_str: str, docs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        hackernews_docs: list[dict[str, Any]] = []
        other_docs: list[dict[str, Any]] = []
        for doc in docs:
            if (doc.get("source") or "").lower() == "hackernews":
                hackernews_docs.append(doc)
            else:
                other_docs.append(doc)

        if not hackernews_docs:
            return docs

        try:
            current_date = date.fromisoformat(date_str)
        except ValueError:
            current_date = today_local()
        yesterday_str = (current_date - timedelta(days=1)).isoformat()
        yesterday_ids = self._rank_snapshots.get_snapshot_doc_ids(
            snapshot_date=yesterday_str,
            source_channel="hn_daily_html",
        )

        if yesterday_ids:
            before_count = len(hackernews_docs)
            hackernews_docs = [
                doc for doc in hackernews_docs if doc.get("id") not in yesterday_ids
            ]
            excluded = before_count - len(hackernews_docs)
            if excluded > 0:
                logging.getLogger(__name__).info(
                    "[HN Daily] 排除昨日(%s)已上榜条目 %d 条，剩余 %d 条",
                    yesterday_str,
                    excluded,
                    len(hackernews_docs),
                )

        hackernews_docs.sort(
            key=lambda doc: float(doc.get("raw_score") or doc.get("score") or 0),
            reverse=True,
        )
        return other_docs + hackernews_docs
