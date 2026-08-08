from __future__ import annotations

"""X 日榜快照补拉（历史日期重建）管理服务。

背景：X 采集 2026-08-06 才上线，首批回填推文（发布于 7 月下旬~8 月初）
只落了 documents 表、从未进入任何日榜快照——采集器
filter_tweets_to_snapshot_date 只把「采集当天（CST）发布」的推文写进当天
快照，历史日期因此永远空白。本服务按同一 CST 物理日约定把已入库推文
重新归属到各自发布日，补写 document_rank_snapshots，使 X 看板日期模式
可以翻到采集上线之前。

幂等性：upsert_rank_snapshot 冲突语义为 LEAST(rank_in_period) /
GREATEST(raw_score, score)，重复补拉或覆盖采集器已写入的更优数据均安全。
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.repositories.document_repository import (
    DocumentXSnapshotBackfillReader,
)
from backend.app.repositories.rank_snapshot_repository import RankSnapshotWriter

logger = logging.getLogger(__name__)

X_DAILY_CHANNEL = "x_daily_watchlist"

_TZ_CST = timezone(timedelta(hours=8))


def _cst_day(value: Any) -> str:
    """published_at ISO 串 → CST 日历日；空值/无法解析返回空串。"""
    if not isinstance(value, str) or not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_TZ_CST).date().isoformat()


def _to_float(value: Any) -> float:
    try:
        result = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return result


def _engagement_score(row: dict[str, Any]) -> float:
    """互动分优先取 raw_score（与看板 tweetScore 同口径），缺失回退 score。"""
    raw = _to_float(row.get("raw_score"))
    return raw if raw else _to_float(row.get("score"))


class XSnapshotAdminService:
    """Rebuild x_daily_watchlist snapshots from already-ingested tweets."""

    def __init__(
        self,
        *,
        documents: DocumentXSnapshotBackfillReader,
        rank_snapshots: RankSnapshotWriter,
    ) -> None:
        self._documents = documents
        self._rank_snapshots = rank_snapshots

    def rebuild(self, target_date: str | None = None) -> dict[str, Any]:
        """按发布日（CST）重建快照；target_date 为空时重建全部历史日期。

        返回 {"results": [{"date", "upserted"}...按日期升序], "skipped_no_date": n}
        ——skipped_no_date 统计 published_at 缺失/无法解析、无法归属日期的存量。
        """
        rows = self._documents.list_x_snapshot_backfill_rows()
        grouped: dict[str, list[dict[str, Any]]] = {}
        skipped_no_date = 0
        for row in rows:
            day = _cst_day(row.get("published_at"))
            if not day:
                skipped_no_date += 1
                continue
            if target_date and day != target_date:
                continue
            if not row.get("id"):
                continue
            grouped.setdefault(day, []).append(row)

        results: list[dict[str, Any]] = []
        for day in sorted(grouped):
            docs = sorted(
                grouped[day], key=_engagement_score, reverse=True
            )
            for rank, doc in enumerate(docs, start=1):
                self._rank_snapshots.upsert_rank_snapshot(
                    doc_id=str(doc["id"]),
                    snapshot_date=day,
                    source_channel=X_DAILY_CHANNEL,
                    rank_in_period=rank,
                    raw_score=_engagement_score(doc),
                    score=_to_float(doc.get("score")),
                )
            results.append({"date": day, "upserted": len(docs)})

        logger.info(
            "[XSnapshotRebuild] target=%s, dates=%d, upserted=%d, skipped_no_date=%d",
            target_date or "ALL",
            len(results),
            sum(item["upserted"] for item in results),
            skipped_no_date,
        )
        return {"results": results, "skipped_no_date": skipped_no_date}
