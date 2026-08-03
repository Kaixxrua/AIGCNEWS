from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

from backend.app.core.config import settings
from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)

_MINIMUM_SCHEMA_VERSION = 10
_MAX_BATCH_SIZE = 1000
_SAMPLE_LIMIT = 20
_ADVISORY_LOCK_ID = 3_704_219_885_127_739_101
_LEGACY_CORRUPTION_END_DATE = "2026-07-30"


class GitHubWatcherRepairSafetyError(RuntimeError):
    """Raised when watcher repair preconditions are not satisfied."""


class GitHubWatcherCorruptionRepairService:
    """Quarantine snapshots that stored stars as GitHub subscribers."""

    def __init__(
        self,
        *,
        postgres: PostgresDatabaseLifecycle = postgres_database,
        config: Any = settings,
    ) -> None:
        self._postgres = postgres
        self._config = config

    def repair(
        self,
        *,
        target_database: str,
        target_schema: str,
        batch_size: int = 500,
        after_snapshot_date: str = "",
        after_repo_id: str = "",
        apply: bool = False,
        production_authorized: bool = False,
    ) -> dict[str, Any]:
        batch_size = self._validate_batch_size(batch_size)
        cursor = self._validate_cursor(after_snapshot_date, after_repo_id)
        if apply:
            self._validate_production_authorization(production_authorized)

        with self._postgres.transaction() as connection:
            target = self._inspect_target(
                connection,
                target_database=target_database,
                target_schema=target_schema,
            )
            if apply:
                with connection.cursor() as db_cursor:
                    db_cursor.execute(
                        "SELECT pg_try_advisory_xact_lock(%s) AS acquired",
                        (_ADVISORY_LOCK_ID,),
                    )
                    lock_row = db_cursor.fetchone() or {}
                if not bool(self._row_value(lock_row, "acquired")):
                    raise GitHubWatcherRepairSafetyError(
                        "another GitHub watcher repair is already running"
                    )

            rows = self._find_corrupted_snapshots(
                connection,
                batch_size=batch_size,
                cursor=cursor,
                for_update=apply,
            )
            selected = rows
            counts = {
                "snapshots_quarantined": 0,
                "candidates_cleared": 0,
                "daily_watchers_cleared": 0,
                "daily_metrics_rebuilt": 0,
            }
            if apply and selected:
                counts = self._apply_batch(connection, selected)
            next_cursor = (
                str(selected[-1]["snapshot_date"]),
                str(selected[-1]["repo_id"]),
            ) if selected else cursor
            has_more = self._has_corrupted_snapshots_after(
                connection,
                cursor=next_cursor,
            )
            if apply and not has_more:
                remaining = self._find_corrupted_snapshots(
                    connection,
                    batch_size=1,
                    cursor=None,
                    for_update=False,
                )
                if remaining:
                    raise GitHubWatcherRepairSafetyError(
                        "corrupted snapshots remain behind the repair cursor"
                    )

        next_cursor = None
        if selected:
            next_cursor = {
                "snapshot_date": str(selected[-1]["snapshot_date"]),
                "repo_id": str(selected[-1]["repo_id"]),
            }
        return {
            "status": "ready",
            "applied": bool(apply),
            "target_database": target["database"],
            "target_schema": target["schema"],
            "schema_version": target["schema_version"],
            "batch_size": batch_size,
            "matched": len(selected),
            "has_more": has_more,
            "next_cursor": next_cursor,
            "samples": [
                {
                    "repo_id": str(row["repo_id"]),
                    "snapshot_date": str(row["snapshot_date"]),
                    "stars": int(row["stars"]),
                    "watchers": int(row["watchers"]),
                }
                for row in selected[:_SAMPLE_LIMIT]
            ],
            **counts,
        }

    def _inspect_target(
        self,
        connection: Any,
        *,
        target_database: str,
        target_schema: str,
    ) -> dict[str, Any]:
        if not target_database.strip() or not target_schema.strip():
            raise GitHubWatcherRepairSafetyError(
                "target database and schema confirmations are required"
            )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database() AS database, current_schema() AS schema"
            )
            identity = cursor.fetchone() or {}
            cursor.execute(
                "SELECT COALESCE(MAX(version), 0) AS version "
                "FROM app_schema_migrations"
            )
            migration = cursor.fetchone() or {}
        database = str(self._row_value(identity, "database") or "")
        schema = str(self._row_value(identity, "schema", 1) or "")
        version = int(self._row_value(migration, "version") or 0)
        if database != target_database or schema != target_schema:
            raise GitHubWatcherRepairSafetyError(
                "target database/schema confirmation does not match the active connection"
            )
        if version < _MINIMUM_SCHEMA_VERSION:
            raise GitHubWatcherRepairSafetyError(
                "PostgreSQL schema is below the required watcher repair version"
            )
        return {"database": database, "schema": schema, "schema_version": version}

    @staticmethod
    def _find_corrupted_snapshots(
        connection: Any,
        *,
        batch_size: int,
        cursor: tuple[str, str] | None,
        for_update: bool,
    ) -> list[dict[str, Any]]:
        cursor_sql = ""
        params: list[Any] = [_LEGACY_CORRUPTION_END_DATE]
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

    @staticmethod
    def _has_corrupted_snapshots_after(
        connection: Any,
        *,
        cursor: tuple[str, str] | None,
    ) -> bool:
        cursor_sql = ""
        params: tuple[Any, ...] = (_LEGACY_CORRUPTION_END_DATE,)
        if cursor is not None:
            cursor_sql = " AND (snapshot_date, repo_id) > (%s, %s)"
            params = (_LEGACY_CORRUPTION_END_DATE, *cursor)
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
        return bool(GitHubWatcherCorruptionRepairService._row_value(row, "has_more"))

    @staticmethod
    def _apply_batch(
        connection: Any,
        rows: list[dict[str, Any]],
    ) -> dict[str, int]:
        snapshot_ids = [int(row["id"]) for row in rows]
        repo_ids = sorted({str(row["repo_id"]) for row in rows})
        snapshot_keys = sorted(
            {(str(row["repo_id"]), str(row["snapshot_date"])) for row in rows}
        )
        affected_keys = set(snapshot_keys)
        for repo_id, snapshot_date in snapshot_keys:
            affected_keys.add(
                (repo_id, (date.fromisoformat(snapshot_date) + timedelta(days=1)).isoformat())
            )
        current_repo_ids = [key[0] for key in snapshot_keys]
        current_dates = [key[1] for key in snapshot_keys]
        affected_repo_ids = [key[0] for key in sorted(affected_keys)]
        affected_dates = [key[1] for key in sorted(affected_keys)]

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE github_repo_snapshots "
                "SET watchers=0,community_metrics_complete=FALSE "
                "WHERE id=ANY(%s) AND community_metrics_complete IS TRUE "
                "AND watchers=stars AND stars>=500",
                (snapshot_ids,),
            )
            snapshots_quarantined = cursor.rowcount

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
            candidates_cleared = cursor.rowcount

            cursor.execute(
                "WITH affected(repo_id,metric_date) AS ("
                "SELECT * FROM UNNEST(%s::text[],%s::text[])) "
                "UPDATE github_repo_daily_metrics AS metrics SET watchers=0 "
                "FROM affected WHERE metrics.repo_id=affected.repo_id "
                "AND metrics.metric_date=affected.metric_date",
                (current_repo_ids, current_dates),
            )
            daily_watchers_cleared = cursor.rowcount

            cursor.execute(
                "WITH affected(repo_id,metric_date) AS ("
                "SELECT * FROM UNNEST(%s::text[],%s::text[])) "
                "UPDATE github_repo_daily_metrics AS metrics SET "
                "daily_fork_growth=0,daily_watcher_growth=0,"
                "community_engagement_score=0.0,"
                "hot_score=ROUND(("
                "0.55*scale_corrected_growth_score+"
                "0.20*growth_acceleration_score+"
                "0.10*absolute_growth_score+"
                "0.10*maintenance_activity_score"
                ")::numeric,4)::double precision,"
                "updated_at=CURRENT_TIMESTAMP::text "
                "FROM affected WHERE metrics.repo_id=affected.repo_id "
                "AND metrics.metric_date=affected.metric_date",
                (affected_repo_ids, affected_dates),
            )
            daily_metrics_rebuilt = cursor.rowcount

        if snapshots_quarantined != len(rows):
            raise GitHubWatcherRepairSafetyError(
                "corrupted snapshot set changed during repair"
            )
        return {
            "snapshots_quarantined": snapshots_quarantined,
            "candidates_cleared": candidates_cleared,
            "daily_watchers_cleared": daily_watchers_cleared,
            "daily_metrics_rebuilt": daily_metrics_rebuilt,
        }

    def _validate_production_authorization(self, cli_authorized: bool) -> None:
        environment = str(getattr(self._config, "env", "development") or "").lower()
        env_authorized = os.getenv(
            "GITHUB_WATCHER_REPAIR_PRODUCTION_AUTHORIZED", ""
        ).strip().lower() in {"1", "true", "yes"}
        if environment == "production" and not (cli_authorized and env_authorized):
            raise GitHubWatcherRepairSafetyError(
                "production watcher repair requires independent CLI and environment authorization"
            )

    @staticmethod
    def _validate_batch_size(batch_size: int) -> int:
        value = int(batch_size)
        if value < 1 or value > _MAX_BATCH_SIZE:
            raise GitHubWatcherRepairSafetyError(
                f"batch size must be between 1 and {_MAX_BATCH_SIZE}"
            )
        return value

    @staticmethod
    def _validate_cursor(
        snapshot_date: str,
        repo_id: str,
    ) -> tuple[str, str] | None:
        clean_date = str(snapshot_date or "").strip()
        clean_repo = str(repo_id or "").strip()
        if bool(clean_date) != bool(clean_repo):
            raise GitHubWatcherRepairSafetyError(
                "both cursor snapshot date and repository ID are required"
            )
        if not clean_date:
            return None
        try:
            date.fromisoformat(clean_date)
        except ValueError as exc:
            raise GitHubWatcherRepairSafetyError(
                "cursor snapshot date must use YYYY-MM-DD"
            ) from exc
        if len(clean_repo) > 255:
            raise GitHubWatcherRepairSafetyError(
                "cursor repository ID must be at most 255 characters"
            )
        return clean_date, clean_repo

    @staticmethod
    def _row_value(row: Any, key: str, index: int = 0) -> Any:
        if isinstance(row, dict):
            return row.get(key)
        return row[index] if row is not None else None
