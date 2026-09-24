from __future__ import annotations

from typing import Any

from backend.app.domain.github_heat import (
    MAGNITUDE_WEIGHTS,
    QUALITY_BASE,
    QUALITY_SPAN,
    QUALITY_WEIGHTS,
    SCORE_VERSION,
    SUSPICION_DEMOTION_STRENGTH,
    SUSPICION_DEMOTION_THRESHOLD,
)

# daily_hot_v6 display stretch, kept only to repair rows still labelled v6.
_V6_DISPLAY_ANCHORS = (
    (0, 0), (20, 25), (40, 45), (60, 65), (70, 77),
    (80, 85), (85, 90), (90, 93), (95, 96), (100, 100),
)


class PostgresGitHubWatcherRepairRepository:
    """PostgreSQL statements for the GitHub watcher corruption repair tool.

    The repair service owns the transaction boundary: the advisory lock and
    the FOR UPDATE row locks must share one transaction with the batch
    updates, so every method executes on a caller-provided connection
    instead of opening its own transaction.
    """

    def fetch_target_identity(self, connection: Any) -> dict[str, Any]:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database() AS database, current_schema() AS schema"
            )
            row = cursor.fetchone() or {}
        return {
            "database": self._row_value(row, "database"),
            "schema": self._row_value(row, "schema", 1),
        }

    def fetch_schema_version(self, connection: Any) -> Any:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(MAX(version), 0) AS version "
                "FROM app_schema_migrations"
            )
            row = cursor.fetchone() or {}
        return self._row_value(row, "version")

    def try_acquire_repair_lock(self, connection: Any, lock_id: int) -> bool:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_try_advisory_xact_lock(%s) AS acquired",
                (lock_id,),
            )
            row = cursor.fetchone() or {}
        return bool(self._row_value(row, "acquired"))

    def find_corrupted_snapshots(
        self,
        connection: Any,
        *,
        corruption_end_date: str,
        batch_size: int,
        cursor: tuple[str, str] | None,
        for_update: bool,
    ) -> list[dict[str, Any]]:
        cursor_sql = ""
        params: list[Any] = [corruption_end_date]
        if cursor is not None:
            cursor_sql = " AND (snapshot_date, repo_id) > (%s, %s)"
            params.extend(cursor)
        params.append(batch_size)
        lock_sql = " FOR UPDATE" if for_update else ""
        with connection.cursor() as db_cursor:
            db_cursor.execute(
                "SELECT id,repo_id,snapshot_date,stars,watchers "
                "FROM github_repo_snapshots "
                "WHERE community_metrics_complete IS TRUE "
                "AND watchers=stars AND stars>=500 "
                "AND snapshot_date<=%s"
                + cursor_sql
                + " ORDER BY snapshot_date,repo_id LIMIT %s"
                + lock_sql,
                tuple(params),
            )
            return list(db_cursor.fetchall())

    def has_corrupted_snapshots_after(
        self,
        connection: Any,
        *,
        corruption_end_date: str,
        cursor: tuple[str, str] | None,
    ) -> bool:
        cursor_sql = ""
        params: tuple[Any, ...] = (corruption_end_date,)
        if cursor is not None:
            cursor_sql = " AND (snapshot_date, repo_id) > (%s, %s)"
            params = (corruption_end_date, *cursor)
        with connection.cursor() as db_cursor:
            db_cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM github_repo_snapshots "
                "WHERE community_metrics_complete IS TRUE "
                "AND watchers=stars AND stars>=500 "
                "AND snapshot_date<=%s"
                + cursor_sql
                + ") AS has_more",
                params,
            )
            row = db_cursor.fetchone() or {}
        return bool(self._row_value(row, "has_more"))

    def quarantine_corrupted_snapshots(
        self,
        connection: Any,
        snapshot_ids: list[int],
    ) -> int:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE github_repo_snapshots "
                "SET watchers=0,community_metrics_complete=FALSE "
                "WHERE id=ANY(%s) AND community_metrics_complete IS TRUE "
                "AND watchers=stars AND stars>=500",
                (snapshot_ids,),
            )
            return int(cursor.rowcount)

    def reset_candidate_watchers(
        self,
        connection: Any,
        repo_ids: list[str],
    ) -> int:
        with connection.cursor() as cursor:
            cursor.execute(
                "WITH latest_complete AS ("
                "SELECT DISTINCT ON (repo_id) repo_id,watchers "
                "FROM github_repo_snapshots "
                "WHERE repo_id=ANY(%s) AND community_metrics_complete IS TRUE "
                "ORDER BY repo_id,snapshot_date DESC,captured_at DESC) "
                "UPDATE github_repo_candidates AS candidate SET "
                "watchers=COALESCE(latest_complete.watchers,0) "
                "FROM (SELECT UNNEST(%s::text[]) repo_id) affected "
                "LEFT JOIN latest_complete USING (repo_id) "
                "WHERE candidate.repo_id=affected.repo_id "
                "AND candidate.watchers<>COALESCE(latest_complete.watchers,0)",
                (repo_ids, repo_ids),
            )
            return int(cursor.rowcount)

    def clear_daily_watcher_metrics(
        self,
        connection: Any,
        repo_ids: list[str],
        metric_dates: list[str],
    ) -> int:
        with connection.cursor() as cursor:
            cursor.execute(
                "WITH affected(repo_id,metric_date) AS ("
                "SELECT * FROM UNNEST(%s::text[],%s::text[])) "
                "UPDATE github_repo_daily_metrics AS metrics SET watchers=0 "
                "FROM affected WHERE metrics.repo_id=affected.repo_id "
                "AND metrics.metric_date=affected.metric_date",
                (repo_ids, metric_dates),
            )
            return int(cursor.rowcount)

    def rebuild_daily_community_metrics(
        self,
        connection: Any,
        repo_ids: list[str],
        metric_dates: list[str],
    ) -> int:
        v6_display = "CASE " + " ".join(
            f"WHEN affected.raw <= {upper} THEN {start}+({end}-{start})*(affected.raw-{lower})/({upper}-{lower})"
            for (lower, start), (upper, end) in zip(_V6_DISPLAY_ANCHORS, _V6_DISPLAY_ANCHORS[1:])
        ) + " ELSE 100 END"
        # v7: community becomes unknown and drops out of the quality average.
        maintenance_known = "(maintenance_activity_score>0)"
        v7_hot = (
            f"({MAGNITUDE_WEIGHTS['scale']}*scale_corrected_growth_score+"
            f"{MAGNITUDE_WEIGHTS['absolute']}*absolute_growth_score)"
            f"*({QUALITY_BASE}+{QUALITY_SPAN}*("
            f"{QUALITY_WEIGHTS['trend']}*growth_acceleration_score+"
            f"CASE WHEN {maintenance_known} THEN {QUALITY_WEIGHTS['maintenance']}*maintenance_activity_score ELSE 0 END)"
            f"/({QUALITY_WEIGHTS['trend']}+CASE WHEN {maintenance_known} THEN {QUALITY_WEIGHTS['maintenance']} ELSE 0 END)/100)"
            f"*(CASE WHEN growth_suspicion_score>={SUSPICION_DEMOTION_THRESHOLD} "
            f"THEN 1-{SUSPICION_DEMOTION_STRENGTH}*LEAST(growth_suspicion_score,1) ELSE 1 END)"
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "WITH affected(repo_id,metric_date) AS ("
                "SELECT * FROM UNNEST(%s::text[],%s::text[])), "
                "recalculated AS (SELECT metrics.repo_id,metrics.metric_date,"
                "0.50*scale_corrected_growth_score+0.30*absolute_growth_score+"
                "0.10*growth_acceleration_score+0.05*maintenance_activity_score AS raw "
                "FROM github_repo_daily_metrics metrics JOIN affected USING(repo_id,metric_date)) "
                "UPDATE github_repo_daily_metrics AS metrics SET "
                "daily_fork_growth=0,daily_watcher_growth=0,"
                "community_engagement_score=0.0,"
                f"hot_score=ROUND((CASE WHEN score_version='{SCORE_VERSION}' THEN "
                + v7_hot
                + " WHEN score_version='daily_hot_v6' THEN "
                + v6_display + " ELSE "
                "0.55*scale_corrected_growth_score+"
                "0.20*growth_acceleration_score+"
                "0.10*absolute_growth_score+"
                "0.10*maintenance_activity_score"
                " END)::numeric,4)::double precision,"
                "updated_at=CURRENT_TIMESTAMP::text "
                "FROM recalculated affected WHERE metrics.repo_id=affected.repo_id "
                "AND metrics.metric_date=affected.metric_date",
                (repo_ids, metric_dates),
            )
            return int(cursor.rowcount)

    @staticmethod
    def _row_value(row: Any, key: str, index: int = 0) -> Any:
        if isinstance(row, dict):
            return row.get(key)
        return row[index] if row is not None else None
