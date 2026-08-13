from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Sequence

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.rank_snapshot_repository import (
    SNAPSHOT_PERIOD_CHANNELS,
    RankSnapshotWrite,
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deserialize_row_media(row: dict[str, Any]) -> dict[str, Any]:
    """把 JSON 文本列反序列化：media → 列表，quote/link_card → 对象；失败置 None。"""
    media = row.get("media")
    if isinstance(media, str) and media:
        try:
            row["media"] = json.loads(media)
        except json.JSONDecodeError:
            row["media"] = None
    quote = row.get("quote")
    if isinstance(quote, str) and quote:
        try:
            row["quote"] = json.loads(quote)
        except json.JSONDecodeError:
            row["quote"] = None
    link_card = row.get("link_card")
    if isinstance(link_card, str) and link_card:
        try:
            row["link_card"] = json.loads(link_card)
        except json.JSONDecodeError:
            row["link_card"] = None
    return row


class PostgresRankSnapshotRepository:
    """PostgreSQL persistence for ranked document snapshots."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def upsert_rank_snapshot(
        self,
        doc_id: str,
        snapshot_date: str,
        source_channel: str,
        rank_in_period: int,
        raw_score: float,
        score: float,
    ) -> None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO document_rank_snapshots
                        (doc_id, snapshot_date, source_channel, rank_in_period,
                         raw_score, score, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (doc_id, snapshot_date, source_channel) DO UPDATE SET
                        rank_in_period=LEAST(document_rank_snapshots.rank_in_period,
                                             EXCLUDED.rank_in_period),
                        raw_score=GREATEST(document_rank_snapshots.raw_score,
                                           EXCLUDED.raw_score),
                        score=GREATEST(document_rank_snapshots.score, EXCLUDED.score)
                    """,
                    (
                        doc_id,
                        snapshot_date,
                        source_channel,
                        rank_in_period,
                        raw_score,
                        score,
                        _utcnow(),
                    ),
                )
                cursor.execute(
                    """
                    WITH aggregate AS (
                        SELECT MAX(raw_score) AS max_raw, MAX(score) AS max_score
                        FROM document_rank_snapshots
                        WHERE doc_id = %s AND snapshot_date = %s
                    )
                    UPDATE document_rank_snapshots AS snapshot
                    SET raw_score = aggregate.max_raw, score = aggregate.max_score
                    FROM aggregate
                    WHERE snapshot.doc_id = %s AND snapshot.snapshot_date = %s
                      AND (snapshot.raw_score < aggregate.max_raw
                           OR snapshot.score < aggregate.max_score)
                    """,
                    (doc_id, snapshot_date, doc_id, snapshot_date),
                )

    def get_snapshot_documents(
        self,
        snapshot_date: str,
        source_channel: str | None = None,
        source_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        conditions = ["s.snapshot_date = %s"]
        params: list[Any] = [snapshot_date]
        if source_channel:
            conditions.append("s.source_channel = %s")
            params.append(source_channel)
        if source_type and source_type != "all":
            conditions.append("d.source = %s")
            params.append(source_type)
        params.append(limit)
        sql = f"""
            SELECT d.id, d.source, d.title, d.url, d.summary, d.published_date,
                   d.published_at, d.tags, d.indexed, d.created_at,
                   d.media, d.quote, d.link_card, d.author_avatar_url, d.author_name, d.retweeted_by, d.translation_zh,
                   d.authors, d.arxiv_id,
                   COALESCE(NULLIF(d.stars, 0), NULLIF(gs.stars, 0), c.stars, 0) AS stars,
                   COALESCE(NULLIF(d.forks, 0), NULLIF(gs.forks, 0), c.forks, 0) AS forks,
                   COALESCE(NULLIF(d.language, ''), c.language, '') AS language,
                   d.in_daily, d.in_weekly, d.in_monthly, s.source_channel,
                   s.rank_in_period, s.raw_score, s.score, s.snapshot_date
            FROM document_rank_snapshots s
            JOIN documents d ON s.doc_id = d.id
            LEFT JOIN github_repo_candidates c
              ON d.source = 'github' AND (c.full_name = d.title
                  OR (NULLIF(c.url, '') IS NOT NULL AND c.url = d.url))
            LEFT JOIN (
                SELECT DISTINCT ON (repo_id) repo_id, stars, forks
                FROM github_repo_snapshots
                ORDER BY repo_id, snapshot_date DESC
            ) gs ON gs.repo_id = c.repo_id
            WHERE {' AND '.join(conditions)}
            ORDER BY
                CASE WHEN d.source = 'github' THEN s.rank_in_period ELSE 9999 END ASC,
                CASE WHEN d.source != 'github' THEN -s.raw_score ELSE 0 END ASC,
                s.rank_in_period ASC
            LIMIT %s
        """
        return self._fetch_rows(sql, tuple(params))

    def get_snapshot_dates(
        self,
        limit: int = 60,
        source: str | None = None,
        period: str | None = None,
    ) -> list[str]:
        conditions: list[str] = []
        params: list[Any] = []
        if source:
            conditions.append("d.source = %s")
            params.append(source)
        if period:
            if source:
                channels = SNAPSHOT_PERIOD_CHANNELS.get(source, {}).get(period, ())
            else:
                channels = tuple(
                    channel
                    for period_map in SNAPSHOT_PERIOD_CHANNELS.values()
                    for channel in period_map.get(period, ())
                )
            if not channels:
                return []
            conditions.append("s.source_channel = ANY(%s)")
            params.append(list(channels))
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = self._fetch_rows(
            f"""
            SELECT DISTINCT s.snapshot_date
            FROM document_rank_snapshots s
            JOIN documents d ON s.doc_id = d.id
            {where_clause}
            ORDER BY s.snapshot_date DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return [row["snapshot_date"] for row in rows]

    def get_snapshot_source_counts(self, snapshot_date: str) -> dict[str, int]:
        rows = self._fetch_rows(
            """
            SELECT d.source, COUNT(DISTINCT s.doc_id) AS cnt
            FROM document_rank_snapshots s
            JOIN documents d ON s.doc_id = d.id
            WHERE s.snapshot_date = %s
            GROUP BY d.source
            """,
            (snapshot_date,),
        )
        return {row["source"]: int(row["cnt"]) for row in rows}

    def get_snapshot_doc_ids(
        self,
        snapshot_date: str,
        source_channel: str | None = None,
    ) -> set[str]:
        conditions = ["snapshot_date = %s"]
        params: list[Any] = [snapshot_date]
        if source_channel:
            conditions.append("source_channel = %s")
            params.append(source_channel)
        rows = self._fetch_rows(
            f"SELECT DISTINCT doc_id FROM document_rank_snapshots WHERE {' AND '.join(conditions)}",
            tuple(params),
        )
        return {row["doc_id"] for row in rows}

    def delete_snapshots_by_channel(
        self,
        snapshot_date: str,
        source_channel: str,
    ) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM document_rank_snapshots
                    WHERE snapshot_date = %s AND source_channel = %s
                    """,
                    (snapshot_date, source_channel),
                )
                return int(cursor.rowcount)

    def replace_channel_snapshots(
        self,
        snapshot_date: str,
        source_channel: str,
        snapshots: Sequence[RankSnapshotWrite],
    ) -> int:
        """单事务整 channel 替换：先删旧切片再批量 upsert，崩溃不留残缺榜单。

        upsert 冲突语义与 upsert_rank_snapshot 一致（rank 取 LEAST、分数取
        GREATEST），随后对涉及 doc_id 做一次跨 channel 分数同步；任一步失败
        整体回滚，进程在 delete 后崩溃导致榜单残缺的窗口被彻底关闭。
        """
        rows = [dict(snapshot) for snapshot in snapshots]
        now = _utcnow()
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM document_rank_snapshots
                    WHERE snapshot_date = %s AND source_channel = %s
                    """,
                    (snapshot_date, source_channel),
                )
                if not rows:
                    return 0
                cursor.executemany(
                    """
                    INSERT INTO document_rank_snapshots
                        (doc_id, snapshot_date, source_channel, rank_in_period,
                         raw_score, score, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (doc_id, snapshot_date, source_channel) DO UPDATE SET
                        rank_in_period=LEAST(document_rank_snapshots.rank_in_period,
                                             EXCLUDED.rank_in_period),
                        raw_score=GREATEST(document_rank_snapshots.raw_score,
                                           EXCLUDED.raw_score),
                        score=GREATEST(document_rank_snapshots.score, EXCLUDED.score)
                    """,
                    [
                        (
                            str(row["doc_id"]),
                            snapshot_date,
                            source_channel,
                            int(row["rank_in_period"]),
                            float(row["raw_score"]),
                            float(row["score"]),
                            now,
                        )
                        for row in rows
                    ],
                )
                doc_ids = sorted({str(row["doc_id"]) for row in rows})
                cursor.execute(
                    """
                    WITH aggregate AS (
                        SELECT doc_id, MAX(raw_score) AS max_raw, MAX(score) AS max_score
                        FROM document_rank_snapshots
                        WHERE snapshot_date = %s AND doc_id = ANY(%s)
                        GROUP BY doc_id
                    )
                    UPDATE document_rank_snapshots AS snapshot
                    SET raw_score = aggregate.max_raw, score = aggregate.max_score
                    FROM aggregate
                    WHERE snapshot.doc_id = aggregate.doc_id
                      AND snapshot.snapshot_date = %s
                      AND (snapshot.raw_score < aggregate.max_raw
                           OR snapshot.score < aggregate.max_score)
                    """,
                    (snapshot_date, doc_ids, snapshot_date),
                )
                return len(rows)

    def _fetch_rows(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return [_deserialize_row_media(dict(row)) for row in cursor.fetchall()]
