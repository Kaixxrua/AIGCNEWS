from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.core.database import DatabaseLifecycle
from backend.app.repositories.rank_snapshot_repository import SNAPSHOT_PERIOD_CHANNELS


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class MySQLRankSnapshotRepository:
    """Lifecycle-backed persistence for ranked document snapshots."""

    def __init__(self, database: DatabaseLifecycle) -> None:
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
        upsert_sql = """
            INSERT INTO document_rank_snapshots
                (doc_id, snapshot_date, source_channel, rank_in_period, raw_score, score, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                rank_in_period=LEAST(rank_in_period, VALUES(rank_in_period)),
                raw_score=GREATEST(raw_score, VALUES(raw_score)),
                score=GREATEST(score, VALUES(score))
        """
        sync_sql = """
            UPDATE document_rank_snapshots s
            JOIN (
                SELECT doc_id, snapshot_date,
                       MAX(raw_score) AS max_raw, MAX(score) AS max_score
                FROM document_rank_snapshots
                WHERE doc_id = %s AND snapshot_date = %s
                GROUP BY doc_id, snapshot_date
            ) agg ON s.doc_id = agg.doc_id AND s.snapshot_date = agg.snapshot_date
            SET s.raw_score = agg.max_raw, s.score = agg.max_score
            WHERE s.doc_id = %s AND s.snapshot_date = %s
              AND (s.raw_score < agg.max_raw OR s.score < agg.max_score)
        """
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    upsert_sql,
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
                    sync_sql,
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
        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT
                d.id, d.source, d.title, d.url, d.summary, d.published_date,
                d.tags, d.indexed, d.created_at,
                COALESCE(NULLIF(d.stars, 0), NULLIF(gs.stars, 0), c.stars, 0) AS stars,
                COALESCE(NULLIF(d.forks, 0), NULLIF(gs.forks, 0), c.forks, 0) AS forks,
                COALESCE(NULLIF(d.language, ''), c.language, '') AS language,
                d.in_daily, d.in_weekly, d.in_monthly,
                s.source_channel,
                s.rank_in_period,
                s.raw_score,
                s.score,
                s.snapshot_date
            FROM document_rank_snapshots s
            JOIN documents d ON s.doc_id = d.id
            LEFT JOIN github_repo_candidates c
              ON d.source = 'github'
             AND (c.full_name = d.title OR c.url = d.url)
            LEFT JOIN (
                SELECT snap.repo_id, snap.stars, snap.forks
                FROM github_repo_snapshots snap
                JOIN (
                    SELECT repo_id, MAX(snapshot_date) AS snapshot_date
                    FROM github_repo_snapshots
                    GROUP BY repo_id
                ) latest
                  ON latest.repo_id = snap.repo_id
                 AND latest.snapshot_date = snap.snapshot_date
            ) gs ON gs.repo_id = c.repo_id
            WHERE {where_clause}
            ORDER BY
                CASE WHEN d.source = 'github' THEN s.rank_in_period ELSE 9999 END ASC,
                CASE WHEN d.source != 'github' THEN -s.raw_score ELSE 0 END ASC,
                s.rank_in_period ASC
            LIMIT %s
        """
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                return list(cursor.fetchall())

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
            placeholders = ", ".join(["%s"] * len(channels))
            conditions.append(f"s.source_channel IN ({placeholders})")
            params.extend(channels)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT DISTINCT s.snapshot_date
            FROM document_rank_snapshots s
            JOIN documents d ON s.doc_id = d.id
            {where_clause}
            ORDER BY s.snapshot_date DESC
            LIMIT %s
        """
        params.append(limit)
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
        return [row["snapshot_date"] for row in rows]

    def get_snapshot_source_counts(self, snapshot_date: str) -> dict[str, int]:
        sql = """
            SELECT d.source, COUNT(DISTINCT s.doc_id) AS cnt
            FROM document_rank_snapshots s
            JOIN documents d ON s.doc_id = d.id
            WHERE s.snapshot_date = %s
            GROUP BY d.source
        """
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (snapshot_date,))
                rows = cursor.fetchall()
        return {row["source"]: row["cnt"] for row in rows}

    def get_snapshot_doc_ids(
        self,
        snapshot_date: str,
        source_channel: str | None = None,
    ) -> set[str]:
        conditions = ["s.snapshot_date = %s"]
        params: list[Any] = [snapshot_date]

        if source_channel:
            conditions.append("s.source_channel = %s")
            params.append(source_channel)

        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT DISTINCT s.doc_id
            FROM document_rank_snapshots s
            WHERE {where_clause}
        """
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
        return {row["doc_id"] for row in rows}

    def delete_snapshots_by_channel(
        self,
        snapshot_date: str,
        source_channel: str,
    ) -> int:
        sql = """
            DELETE FROM document_rank_snapshots
            WHERE snapshot_date = %s AND source_channel = %s
        """
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (snapshot_date, source_channel))
                return cursor.rowcount
