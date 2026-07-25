from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from backend.app.repositories.rank_snapshot_repository import RankSnapshotReader
from backend.app.services.dashboard.policy import today_local

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
}

SAME_PERIOD_FALLBACKS: dict[str, dict[str, tuple[str, ...]]] = {
    "github": {
        "daily": ("github_hot_daily", "github_fallback"),
        "weekly": ("github_hot_weekly",),
        "monthly": ("github_hot_monthly",),
    }
}


class DashboardQueryService:
    def __init__(self, rank_snapshots: RankSnapshotReader) -> None:
        self._rank_snapshots = rank_snapshots

    def get_docs_for_date(
        self,
        date_str: str,
        period: str,
        source_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        all_snapshot_docs: list[dict[str, Any]] = []

        if source_type and source_type != "all":
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
