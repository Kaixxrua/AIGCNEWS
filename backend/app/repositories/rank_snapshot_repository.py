from __future__ import annotations

from typing import Any, Protocol

SNAPSHOT_PERIOD_CHANNELS: dict[str, dict[str, tuple[str, ...]]] = {
    "arxiv": {
        "daily": ("huggingface_daily_html",),
        "weekly": ("huggingface_weekly_html",),
        "monthly": ("huggingface_monthly_html",),
    },
    "github": {
        "daily": ("github_trending_daily", "github_hot_daily", "github_fallback"),
        "weekly": ("github_trending_weekly", "github_hot_weekly"),
        "monthly": ("github_trending_monthly", "github_hot_monthly"),
    },
    "news": {"daily": ("techmeme_daily_rss",)},
    "producthunt": {
        "daily": ("producthunt_daily_html",),
        "weekly": ("producthunt_weekly_html",),
        "monthly": ("producthunt_monthly_html",),
    },
    "hackernews": {
        "daily": ("hn_daily_html",),
        "weekly": ("hn_weekly_html",),
        "monthly": ("hn_monthly_html",),
    },
}


class RankSnapshotReader(Protocol):
    """Read historical ranked document snapshots."""

    def get_snapshot_documents(
        self,
        snapshot_date: str,
        source_channel: str | None = None,
        source_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]: ...

    def get_snapshot_dates(
        self,
        limit: int = 60,
        source: str | None = None,
        period: str | None = None,
    ) -> list[str]: ...

    def get_snapshot_source_counts(self, snapshot_date: str) -> dict[str, int]: ...

    def get_snapshot_doc_ids(
        self,
        snapshot_date: str,
        source_channel: str | None = None,
    ) -> set[str]: ...


class RankSnapshotWriter(Protocol):
    """Persist one ranked document and synchronize its cross-channel score."""

    def upsert_rank_snapshot(
        self,
        doc_id: str,
        snapshot_date: str,
        source_channel: str,
        rank_in_period: int,
        raw_score: float,
        score: float,
    ) -> None: ...


class RankSnapshotAdminWriter(Protocol):
    """Delete a channel slice before replacement ingestion."""

    def delete_snapshots_by_channel(
        self,
        snapshot_date: str,
        source_channel: str,
    ) -> int: ...


class RankSnapshotRepository(
    RankSnapshotReader,
    RankSnapshotWriter,
    RankSnapshotAdminWriter,
    Protocol,
):
    """Combined rank snapshot persistence boundary."""
