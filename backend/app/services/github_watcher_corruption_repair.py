from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.app.core.config import settings
from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)
from backend.app.repositories.postgres_github_watcher_repair_repository import (
    PostgresGitHubWatcherRepairRepository,
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
        repository: PostgresGitHubWatcherRepairRepository | None = None,
    ) -> None:
        self._postgres = postgres
        self._config = config
        self._repository = repository or PostgresGitHubWatcherRepairRepository()

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
                if not self._repository.try_acquire_repair_lock(
                    connection, _ADVISORY_LOCK_ID
                ):
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
        identity = self._repository.fetch_target_identity(connection)
        version = int(self._repository.fetch_schema_version(connection) or 0)
        database = str(identity["database"] or "")
        schema = str(identity["schema"] or "")
        if database != target_database or schema != target_schema:
            raise GitHubWatcherRepairSafetyError(
                "target database/schema confirmation does not match the active connection"
            )
        if version < _MINIMUM_SCHEMA_VERSION:
            raise GitHubWatcherRepairSafetyError(
                "PostgreSQL schema is below the required watcher repair version"
            )
        return {"database": database, "schema": schema, "schema_version": version}

    def _find_corrupted_snapshots(
        self,
        connection: Any,
        *,
        batch_size: int,
        cursor: tuple[str, str] | None,
        for_update: bool,
    ) -> list[dict[str, Any]]:
        return self._repository.find_corrupted_snapshots(
            connection,
            corruption_end_date=_LEGACY_CORRUPTION_END_DATE,
            batch_size=batch_size,
            cursor=cursor,
            for_update=for_update,
        )

    def _has_corrupted_snapshots_after(
        self,
        connection: Any,
        *,
        cursor: tuple[str, str] | None,
    ) -> bool:
        return self._repository.has_corrupted_snapshots_after(
            connection,
            corruption_end_date=_LEGACY_CORRUPTION_END_DATE,
            cursor=cursor,
        )

    def _apply_batch(
        self,
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

        snapshots_quarantined = self._repository.quarantine_corrupted_snapshots(
            connection, snapshot_ids
        )
        candidates_cleared = self._repository.reset_candidate_watchers(
            connection, repo_ids
        )
        daily_watchers_cleared = self._repository.clear_daily_watcher_metrics(
            connection, current_repo_ids, current_dates
        )
        daily_metrics_rebuilt = self._repository.rebuild_daily_community_metrics(
            connection, affected_repo_ids, affected_dates
        )

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
        # 第二授权通道：settings.github_watcher_repair_production_authorized
        # （环境变量 GITHUB_WATCHER_REPAIR_PRODUCTION_AUTHORIZED 启动时读取一次）。
        env_authorized = bool(
            getattr(self._config, "github_watcher_repair_production_authorized", False)
        )
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
