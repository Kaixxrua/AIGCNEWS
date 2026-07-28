from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.app.core.database import DatabaseLifecycle, mysql_database
from backend.app.core.postgres_database import PostgresDatabaseLifecycle, postgres_database

@dataclass(frozen=True)
class TableTransferSpec:
    name: str
    columns: tuple[str, ...]
    cursor_columns: tuple[str, ...]
    conflict_columns: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    boolean_columns: tuple[str, ...] = ()
    datetime_columns: tuple[str, ...] = ()
    non_null_default_columns: tuple[str, ...] = ()
    fixed_char_columns: tuple[str, ...] = ()
    identity_column: str | None = None
    natural_key_columns: tuple[str, ...] = ()
    text_cursor_columns: tuple[str, ...] = ()


def _spec(
    name: str,
    columns: tuple[str, ...],
    cursor_columns: tuple[str, ...],
    *,
    conflict_columns: tuple[str, ...] | None = None,
    dependencies: tuple[str, ...] = (),
    boolean_columns: tuple[str, ...] = (),
    datetime_columns: tuple[str, ...] = (),
    non_null_default_columns: tuple[str, ...] = (),
    fixed_char_columns: tuple[str, ...] = (),
    identity_column: str | None = None,
    natural_key_columns: tuple[str, ...] = (),
    text_cursor_columns: tuple[str, ...] = (),
) -> TableTransferSpec:
    return TableTransferSpec(
        name=name,
        columns=columns,
        cursor_columns=cursor_columns,
        conflict_columns=conflict_columns or cursor_columns,
        dependencies=dependencies,
        boolean_columns=boolean_columns,
        datetime_columns=datetime_columns,
        non_null_default_columns=non_null_default_columns,
        fixed_char_columns=fixed_char_columns,
        identity_column=identity_column,
        natural_key_columns=natural_key_columns,
        text_cursor_columns=text_cursor_columns or tuple(
            column
            for column in cursor_columns
            if column in {"repo_id", "alias_repo_id", "metric_date"}
        ),
    )


TABLE_TRANSFER_SPECS = (
    _spec(
        "github_repo_candidates",
        (
            "repo_id", "full_name", "title", "url", "description", "language",
            "topics_json", "created_at", "pushed_at", "stars", "forks", "watchers",
            "source_channels", "first_seen_at", "last_seen_at", "last_snapshot_at",
            "availability_status", "not_found_count", "availability_checked_at",
        ),
        ("repo_id",),
        text_cursor_columns=("repo_id",),
        non_null_default_columns=("stars", "forks", "watchers", "source_channels"),
        natural_key_columns=("full_name",),
    ),
    _spec(
        "github_repo_aliases",
        ("alias_repo_id", "canonical_repo_id", "full_name", "created_at", "updated_at"),
        ("alias_repo_id",),
        dependencies=("github_repo_candidates",),
        text_cursor_columns=("alias_repo_id",),
    ),
    _spec(
        "github_repo_enrichments",
        (
            "repo_id", "category_slug", "category_name", "subcategory_slug",
            "subcategory_name", "description_zh", "tags_json", "confidence",
            "source_fingerprint", "prompt_version", "model_provider", "model_name",
            "status", "error_msg", "enriched_at", "updated_at",
        ),
        ("repo_id",),
        dependencies=("github_repo_candidates",),
        non_null_default_columns=("confidence", "model_provider", "model_name"),
    ),
    _spec(
        "github_repo_snapshots",
        (
            "id", "repo_id", "snapshot_date", "captured_at", "stars", "forks",
            "watchers", "community_metrics_complete", "open_issues", "repo_created_at",
            "repo_pushed_at",
        ),
        ("id",),
        dependencies=("github_repo_candidates",),
        boolean_columns=("community_metrics_complete",),
        non_null_default_columns=("stars", "forks", "watchers", "open_issues"),
        identity_column="id",
        natural_key_columns=("repo_id", "snapshot_date"),
    ),
    _spec(
        "github_repo_daily_metrics",
        (
            "repo_id", "metric_date", "stars", "forks", "watchers", "open_issues",
            "previous_snapshot_date", "previous_stars", "daily_star_growth",
            "daily_fork_growth", "daily_watcher_growth", "daily_growth_available",
            "daily_growth_source", "daily_growth_observed_at",
            "scale_corrected_growth_score", "growth_acceleration_score",
            "absolute_growth_score", "maintenance_activity_score",
            "community_engagement_score", "hot_score", "score_version", "updated_at",
        ),
        ("repo_id", "metric_date"),
        dependencies=("github_repo_candidates",),
        text_cursor_columns=("repo_id", "metric_date"),
        boolean_columns=("daily_growth_available",),
        non_null_default_columns=(
            "stars", "forks", "watchers", "open_issues", "previous_stars",
            "daily_star_growth", "daily_fork_growth", "daily_watcher_growth",
            "scale_corrected_growth_score", "growth_acceleration_score",
            "absolute_growth_score", "maintenance_activity_score",
            "community_engagement_score", "hot_score",
        ),
    ),
    _spec(
        "github_trending_hits",
        (
            "id", "repo_id", "full_name", "period", "language", "rank",
            "observed_date", "captured_at", "period_star_growth",
            "period_growth_observed_at",
        ),
        ("id",),
        dependencies=("github_repo_candidates",),
        identity_column="id",
        natural_key_columns=("repo_id", "period", "observed_date"),
    ),
    _spec(
        "github_repo_recommendations",
        ("repo_id", "active", "recommended_by_user_id", "recommended_at", "updated_at"),
        ("repo_id",),
        dependencies=("github_repo_candidates",),
        boolean_columns=("active",),
        datetime_columns=("recommended_at", "updated_at"),
    ),
    _spec(
        "github_project_semantic_sources",
        (
            "repo_id", "readme_text", "readme_sha256", "readme_etag", "readme_status",
            "readme_checked_at", "readme_fetched_at", "readme_repo_pushed_at",
            "readme_error", "readme_retry_count", "readme_next_retry_at",
            "source_fingerprint", "indexed_fingerprint", "index_version",
            "embedding_provider", "embedding_model", "embedding_dimension", "chunk_count",
            "index_status", "index_error", "index_retry_count", "index_next_retry_at",
            "indexed_at", "updated_at",
        ),
        ("repo_id",),
        dependencies=("github_repo_candidates",),
        datetime_columns=(
            "readme_checked_at",
            "readme_fetched_at",
            "readme_repo_pushed_at",
            "readme_next_retry_at",
            "index_next_retry_at",
            "indexed_at",
            "updated_at",
        ),
        non_null_default_columns=("readme_sha256",),
        fixed_char_columns=("readme_sha256",),
    ),
    _spec(
        "tool_websites",
        (
            "id", "canonical_url", "normalized_url_hash", "domain", "title",
            "description", "image_url", "raw_metadata_json", "fetch_status", "fetch_error",
            "source_fingerprint", "visibility", "added_by_user_id", "first_seen_at",
            "last_seen_at", "updated_at",
        ),
        ("id",),
        non_null_default_columns=("title", "image_url"),
        identity_column="id",
        natural_key_columns=("normalized_url_hash",),
    ),
    _spec(
        "tool_website_enrichments",
        (
            "website_id", "category_slug", "category_name", "subcategory_slug",
            "subcategory_name", "description_zh", "tags_json", "confidence",
            "source_fingerprint", "prompt_version", "model_provider", "model_name",
            "status", "error_msg", "enriched_at", "updated_at",
        ),
        ("website_id",),
        dependencies=("tool_websites",),
        non_null_default_columns=("confidence", "model_provider", "model_name"),
    ),
    _spec(
        "project_favorites",
        ("id", "user_id", "project_source", "project_id", "created_at"),
        ("id",),
        datetime_columns=("created_at",),
        identity_column="id",
        natural_key_columns=("user_id", "project_source", "project_id"),
    ),
    _spec(
        "user_tool_websites",
        ("id", "user_id", "website_id", "added_via", "created_at", "updated_at"),
        ("id",),
        dependencies=("tool_websites",),
        datetime_columns=("created_at", "updated_at"),
        identity_column="id",
        natural_key_columns=("user_id", "website_id"),
    ),
    _spec(
        "user_tool_website_overrides",
        (
            "id", "user_id", "website_id", "title", "description", "image_url",
            "description_zh", "category_slug", "category_name", "subcategory_slug",
            "subcategory_name", "tags_json", "created_at", "updated_at",
        ),
        ("id",),
        dependencies=("tool_websites",),
        datetime_columns=("created_at", "updated_at"),
        non_null_default_columns=(
            "title", "image_url", "description_zh", "category_slug", "category_name",
            "subcategory_slug", "subcategory_name",
        ),
        identity_column="id",
        natural_key_columns=("user_id", "website_id"),
    ),
)
TABLE_TRANSFER_SPEC_BY_NAME: Mapping[str, TableTransferSpec] = MappingProxyType(
    {spec.name: spec for spec in TABLE_TRANSFER_SPECS}
)
CANDIDATE_TABLE = "github_repo_candidates"
CANDIDATE_SPEC = TABLE_TRANSFER_SPEC_BY_NAME[CANDIDATE_TABLE]
CANDIDATE_COLUMNS = CANDIDATE_SPEC.columns
MIN_TRANSFER_SCHEMA_VERSION = 3
DEFAULT_BATCH_SIZE = 500
MAX_BATCH_SIZE = 5_000
DEFAULT_MAX_ATTEMPTS = 5
_TRANSIENT_SQLSTATES = {"40001", "40P01", "55P03"}


class ProjectCatalogTransferError(RuntimeError):
    """Raised when a catalog transfer cannot proceed safely."""


class ProjectCatalogTransferSafetyError(ProjectCatalogTransferError):
    """Raised when source, target, or operator confirmation is unsafe."""


class ProjectCatalogTransferCollisionError(ProjectCatalogTransferError):
    """Raised when source identity conflicts with an existing target row."""


@dataclass(frozen=True)
class TargetIdentity:
    database: str
    schema: str
    schema_version: int


@dataclass(frozen=True)
class CandidateCheckpoint:
    cursor: str
    rows_processed: int
    batches_processed: int
    status: str
    source_prefix_digest: str = "0" * 64


@dataclass(frozen=True)
class TableCheckpoint:
    cursor: dict[str, Any]
    rows_processed: int
    batches_processed: int
    status: str
    source_prefix_digest: str = "0" * 64


def source_identity_sha256(config: Any) -> str:
    payload = {
        "database": str(getattr(config, "mysql_database", "")),
        "host": str(getattr(config, "mysql_host", "")),
        "port": int(getattr(config, "mysql_port", 3306)),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def table_batch_digest(
    spec: TableTransferSpec, rows: Iterable[dict[str, Any]]
) -> str:
    digest = hashlib.sha256()
    for row in rows:
        encoded = json.dumps(
            [row.get(column) for column in spec.columns],
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def candidate_batch_digest(rows: Iterable[dict[str, Any]]) -> str:
    return table_batch_digest(CANDIDATE_SPEC, rows)


def extend_table_prefix_digest(
    previous: str,
    spec: TableTransferSpec,
    rows: Iterable[dict[str, Any]],
) -> str:
    digest = hashlib.sha256()
    digest.update(bytes.fromhex(previous))
    digest.update(bytes.fromhex(table_batch_digest(spec, rows)))
    return digest.hexdigest()


def extend_prefix_digest(previous: str, rows: Iterable[dict[str, Any]]) -> str:
    return extend_table_prefix_digest(previous, CANDIDATE_SPEC, rows)


def is_retryable_database_error(error: BaseException) -> bool:
    sqlstate = str(getattr(error, "sqlstate", "") or "")
    if sqlstate.startswith("08") or sqlstate in _TRANSIENT_SQLSTATES:
        return True
    name = type(error).__name__.lower()
    return "operationalerror" in name or "interfaceerror" in name


def _row_value(row: Any, key: str, index: int = 0) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return row[index] if row is not None else None


def _mysql_identifier(value: str) -> str:
    if not value.replace("_", "").isalnum():
        raise ValueError("unsafe MySQL identifier")
    return f"`{value}`"


def _advisory_lock_id(target_database: str, target_schema: str, table_name: str) -> int:
    payload = (
        f"aigcnews:{target_database}:{target_schema}:{table_name}".encode("utf-8")
    )
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big", signed=True)


class ProjectCatalogTransferService:
    """Copy catalog rows from authoritative MySQL into PostgreSQL safely."""

    def __init__(
        self,
        *,
        mysql: DatabaseLifecycle = mysql_database,
        postgres: PostgresDatabaseLifecycle = postgres_database,
        config: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        if config is None:
            from backend.app.core.config import settings

            config = settings
        self._mysql = mysql
        self._postgres = postgres
        self._config = config
        self._sleep = sleep
        self._random_value = random_value

    def plan(
        self,
        *,
        job_id: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        target_database: str,
        target_schema: str,
    ) -> dict[str, Any]:
        job_id = self._validate_job_id(job_id)
        batch_size = self._validate_batch_size(batch_size)
        target = self._inspect_target(target_database, target_schema)
        source_count = self._source_candidate_count()
        target_count = self._target_candidate_count()
        return {
            "status": "dry_run",
            "job_id": job_id,
            "tables": [CANDIDATE_TABLE],
            "batch_size": batch_size,
            "estimated_batches": (source_count + batch_size - 1) // batch_size,
            "source_count": source_count,
            "target_count": target_count,
            "target_database": target.database,
            "target_schema": target.schema,
            "schema_version": target.schema_version,
        }

    def load_candidates(
        self,
        *,
        job_id: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        target_database: str,
        target_schema: str,
        apply: bool = False,
        production_authorized: bool = False,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> dict[str, Any]:
        if not apply:
            return self.plan(
                job_id=job_id,
                batch_size=batch_size,
                target_database=target_database,
                target_schema=target_schema,
            )
        job_id = self._validate_job_id(job_id)
        batch_size = self._validate_batch_size(batch_size)
        self._validate_production_authorization(production_authorized)
        options = {
            "batch_size": batch_size,
            "codec_version": 1,
            "tables": [CANDIDATE_TABLE],
        }
        attempts = max(1, min(int(max_attempts), 10))
        for attempt in range(1, attempts + 1):
            try:
                return self._load_candidates_once(
                    job_id=job_id,
                    options=options,
                    target_database=target_database,
                    target_schema=target_schema,
                )
            except BaseException as error:
                retryable = is_retryable_database_error(error)
                if not retryable or attempt >= attempts:
                    self._record_failure_best_effort(
                        job_id=job_id,
                        attempt=attempt,
                        error=error,
                        retryable=retryable,
                    )
                    raise
                delay = min(0.25 * (2 ** (attempt - 1)), 4.0) * self._random_value()
                self._sleep(delay)
        raise AssertionError("unreachable")

    def plan_catalog(
        self,
        *,
        job_id: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        target_database: str,
        target_schema: str,
        source_timezone: str = "UTC",
    ) -> dict[str, Any]:
        job_id = self._validate_job_id(job_id)
        batch_size = self._validate_batch_size(batch_size)
        self._validate_source_timezone(source_timezone)
        target = self._inspect_target(target_database, target_schema)
        tables = []
        total_source_rows = 0
        for spec in TABLE_TRANSFER_SPECS:
            source_count = self._source_table_count(spec)
            target_count = self._target_table_count(spec)
            total_source_rows += source_count
            tables.append(
                {
                    "table": spec.name,
                    "source_count": source_count,
                    "target_count": target_count,
                    "estimated_batches": (source_count + batch_size - 1) // batch_size,
                }
            )
        return {
            "status": "dry_run",
            "job_id": job_id,
            "tables": tables,
            "batch_size": batch_size,
            "source_timezone": source_timezone,
            "total_source_rows": total_source_rows,
            "target_database": target.database,
            "target_schema": target.schema,
            "schema_version": target.schema_version,
        }

    def load_catalog(
        self,
        *,
        job_id: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        target_database: str,
        target_schema: str,
        source_timezone: str = "UTC",
        apply: bool = False,
        production_authorized: bool = False,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> dict[str, Any]:
        if not apply:
            return self.plan_catalog(
                job_id=job_id,
                batch_size=batch_size,
                target_database=target_database,
                target_schema=target_schema,
                source_timezone=source_timezone,
            )
        job_id = self._validate_job_id(job_id)
        batch_size = self._validate_batch_size(batch_size)
        self._validate_source_timezone(source_timezone)
        self._validate_production_authorization(production_authorized)
        options = {
            "batch_size": batch_size,
            "codec_version": 2,
            "source_timezone": source_timezone,
            "tables": [spec.name for spec in TABLE_TRANSFER_SPECS],
        }
        attempts = max(1, min(int(max_attempts), 10))
        for attempt in range(1, attempts + 1):
            try:
                return self._load_catalog_once(
                    job_id=job_id,
                    options=options,
                    target_database=target_database,
                    target_schema=target_schema,
                )
            except BaseException as error:
                retryable = is_retryable_database_error(error)
                if not retryable or attempt >= attempts:
                    self._record_catalog_failure_best_effort(
                        job_id=job_id,
                        attempt=attempt,
                        error=error,
                        retryable=retryable,
                    )
                    raise
                delay = min(0.25 * (2 ** (attempt - 1)), 4.0) * self._random_value()
                self._sleep(delay)
        raise AssertionError("unreachable")

    def _load_catalog_once(
        self,
        *,
        job_id: str,
        options: dict[str, Any],
        target_database: str,
        target_schema: str,
    ) -> dict[str, Any]:
        lock_ids = [
            _advisory_lock_id(target_database, target_schema, spec.name)
            for spec in TABLE_TRANSFER_SPECS
        ]
        with self._postgres.connection() as connection:
            acquired: list[int] = []
            try:
                for lock_id in lock_ids:
                    self._acquire_lock(connection, lock_id)
                    acquired.append(lock_id)
                target = self._inspect_target_on_connection(
                    connection, target_database, target_schema
                )
                checkpoints = self._ensure_catalog_run_and_checkpoints(
                    connection, job_id=job_id, target=target, options=options
                )
                for spec in TABLE_TRANSFER_SPECS:
                    checkpoint = checkpoints[spec.name]
                    if checkpoint.status == "completed":
                        continue
                    if checkpoint.cursor:
                        current_prefix = self._source_table_prefix_digest(
                            spec,
                            checkpoint.cursor,
                            int(options["batch_size"]),
                            str(options["source_timezone"]),
                        )
                        if current_prefix != checkpoint.source_prefix_digest:
                            raise ProjectCatalogTransferSafetyError(
                                f"source prefix changed after the durable checkpoint for {spec.name}"
                            )
                    elif self._target_table_count_on_connection(connection, spec) != 0:
                        raise ProjectCatalogTransferSafetyError(
                            f"initial load requires an empty target table: {spec.name}"
                        )
                    while True:
                        rows = self._read_table_batch(
                            spec,
                            after=checkpoint.cursor,
                            batch_size=int(options["batch_size"]),
                            source_timezone=str(options["source_timezone"]),
                        )
                        if not rows:
                            self._mark_table_completed(connection, job_id, spec.name)
                            break
                        checkpoint = self._write_table_batch(
                            connection,
                            spec=spec,
                            job_id=job_id,
                            checkpoint=checkpoint,
                            rows=rows,
                        )
                        checkpoints[spec.name] = checkpoint
                sequence_repairs = self._repair_identity_sequences(connection)
                self._mark_catalog_completed(connection, job_id)
                return {
                    "status": "completed",
                    "job_id": job_id,
                    "tables": [spec.name for spec in TABLE_TRANSFER_SPECS],
                    "rows_processed": sum(
                        checkpoint.rows_processed for checkpoint in checkpoints.values()
                    ),
                    "identity_sequences": sequence_repairs,
                }
            finally:
                for lock_id in reversed(acquired):
                    self._release_lock(connection, lock_id)

    def status(self, *, job_id: str) -> dict[str, Any]:
        job_id = self._validate_job_id(job_id)
        with self._postgres.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT r.status AS run_status, r.target_database, r.target_schema,
                           r.schema_version, c.table_name, c.cursor_json,
                           c.rows_processed, c.batches_processed,
                           c.status AS checkpoint_status
                    FROM project_catalog_migration_runs r
                    LEFT JOIN project_catalog_migration_checkpoints c
                      ON c.job_id = r.job_id
                    WHERE r.job_id = %s
                    ORDER BY c.table_name
                    """,
                    (job_id,),
                )
                rows = cursor.fetchall()
        if not rows:
            return {"status": "not_found", "job_id": job_id}
        first = rows[0]
        checkpoints = []
        for row in rows:
            table_name = _row_value(row, "table_name", 4)
            if table_name is None:
                continue
            cursor_json = _row_value(row, "cursor_json", 5) or {}
            if isinstance(cursor_json, str):
                cursor_json = json.loads(cursor_json)
            checkpoints.append(
                {
                    "table": str(table_name),
                    "cursor": cursor_json,
                    "rows_processed": int(_row_value(row, "rows_processed", 6) or 0),
                    "batches_processed": int(_row_value(row, "batches_processed", 7) or 0),
                    "status": str(_row_value(row, "checkpoint_status", 8) or "pending"),
                }
            )
        return {
            "status": str(_row_value(first, "run_status", 0)),
            "job_id": job_id,
            "target_database": str(_row_value(first, "target_database", 1)),
            "target_schema": str(_row_value(first, "target_schema", 2)),
            "schema_version": int(_row_value(first, "schema_version", 3)),
            "checkpoints": checkpoints,
        }

    def verify_candidates(
        self,
        *,
        target_database: str,
        target_schema: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> dict[str, Any]:
        batch_size = self._validate_batch_size(batch_size)
        target = self._inspect_target(target_database, target_schema)
        source_count, source_digest = self._digest_source_candidates(batch_size)
        target_count, target_digest = self._digest_target_candidates(batch_size)
        matches = source_count == target_count and source_digest == target_digest
        return {
            "status": "match" if matches else "mismatch",
            "table": CANDIDATE_TABLE,
            "source_count": source_count,
            "target_count": target_count,
            "source_digest_sha256": source_digest,
            "target_digest_sha256": target_digest,
            "target_database": target.database,
            "target_schema": target.schema,
            "schema_version": target.schema_version,
        }

    def _load_candidates_once(
        self,
        *,
        job_id: str,
        options: dict[str, Any],
        target_database: str,
        target_schema: str,
    ) -> dict[str, Any]:
        lock_id = _advisory_lock_id(
            target_database, target_schema, CANDIDATE_TABLE
        )
        with self._postgres.connection() as connection:
            self._acquire_lock(connection, lock_id)
            try:
                target = self._inspect_target_on_connection(
                    connection, target_database, target_schema
                )
                checkpoint = self._ensure_run_and_checkpoint(
                    connection, job_id=job_id, target=target, options=options
                )
                if checkpoint.cursor:
                    current_prefix = self._source_candidate_prefix_digest(
                        checkpoint.cursor, int(options["batch_size"])
                    )
                    if current_prefix != checkpoint.source_prefix_digest:
                        raise ProjectCatalogTransferSafetyError(
                            "source candidate prefix changed after the durable checkpoint"
                        )
                elif self._target_candidate_count_on_connection(connection) != 0:
                    raise ProjectCatalogTransferSafetyError(
                        "initial candidate load requires an empty target table"
                    )
                while True:
                    rows = self._read_candidate_batch(
                        after_repo_id=checkpoint.cursor,
                        batch_size=int(options["batch_size"]),
                    )
                    if not rows:
                        self._mark_completed(connection, job_id)
                        return {
                            "status": "completed",
                            "job_id": job_id,
                            "table": CANDIDATE_TABLE,
                            "rows_processed": checkpoint.rows_processed,
                            "batches_processed": checkpoint.batches_processed,
                            "cursor": checkpoint.cursor,
                        }
                    checkpoint = self._write_candidate_batch(
                        connection,
                        job_id=job_id,
                        checkpoint=checkpoint,
                        rows=rows,
                    )
            finally:
                self._release_lock(connection, lock_id)

    def _inspect_target(self, database: str, schema: str) -> TargetIdentity:
        with self._postgres.connection() as connection:
            return self._inspect_target_on_connection(connection, database, schema)

    @staticmethod
    def _inspect_target_on_connection(
        connection: Any, expected_database: str, expected_schema: str
    ) -> TargetIdentity:
        if not expected_database.strip() or not expected_schema.strip():
            raise ProjectCatalogTransferSafetyError(
                "target database and schema confirmations are required"
            )
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database() AS database, current_schema() AS schema")
                row = cursor.fetchone()
                database = str(_row_value(row, "database", 0) or "")
                schema = str(_row_value(row, "schema", 1) or "")
                cursor.execute("SELECT COALESCE(MAX(version), 0) AS version FROM app_schema_migrations")
                version_row = cursor.fetchone()
                version = int(_row_value(version_row, "version", 0) or 0)
        if database != expected_database or schema != expected_schema:
            raise ProjectCatalogTransferSafetyError(
                "target database/schema confirmation does not match the active connection"
            )
        if version < MIN_TRANSFER_SCHEMA_VERSION:
            raise ProjectCatalogTransferSafetyError(
                f"PostgreSQL schema version {version} is below required version "
                f"{MIN_TRANSFER_SCHEMA_VERSION}"
            )
        return TargetIdentity(database=database, schema=schema, schema_version=version)

    def _source_candidate_count(self) -> int:
        with self._mysql.transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_mysql_read(cursor)
                cursor.execute(f"SELECT COUNT(*) AS count FROM {CANDIDATE_TABLE}")
                row = cursor.fetchone()
        return int(_row_value(row, "count", 0) or 0)

    def _target_candidate_count(self) -> int:
        with self._postgres.connection() as connection:
            return self._target_candidate_count_on_connection(connection)

    @staticmethod
    def _target_candidate_count_on_connection(connection: Any) -> int:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) AS count FROM {CANDIDATE_TABLE}")
                row = cursor.fetchone()
        return int(_row_value(row, "count", 0) or 0)

    def _source_table_count(self, spec: TableTransferSpec) -> int:
        with self._mysql.transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_mysql_read(cursor)
                cursor.execute(f"SELECT COUNT(*) AS count FROM {spec.name}")
                row = cursor.fetchone()
        return int(_row_value(row, "count", 0) or 0)

    def _target_table_count(self, spec: TableTransferSpec) -> int:
        with self._postgres.connection() as connection:
            return self._target_table_count_on_connection(connection, spec)

    @staticmethod
    def _target_table_count_on_connection(
        connection: Any, spec: TableTransferSpec
    ) -> int:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) AS count FROM {spec.name}")
                row = cursor.fetchone()
        return int(_row_value(row, "count", 0) or 0)

    def _read_table_batch(
        self,
        spec: TableTransferSpec,
        *,
        after: Mapping[str, Any],
        batch_size: int,
        source_timezone: str,
    ) -> list[dict[str, Any]]:
        columns = ", ".join(_mysql_identifier(column) for column in spec.columns)
        cursor_expressions = tuple(
            (
                f"BINARY {_mysql_identifier(column)}"
                if column in spec.text_cursor_columns
                else _mysql_identifier(column)
            )
            for column in spec.cursor_columns
        )
        cursor_sql = ", ".join(cursor_expressions)
        if after:
            placeholders = ", ".join(
                f"BINARY %s" if column in spec.text_cursor_columns else "%s"
                for column in spec.cursor_columns
            )
            where = f"WHERE ({cursor_sql}) > ({placeholders})"
            params = tuple(after[column] for column in spec.cursor_columns) + (batch_size,)
        else:
            where = ""
            params = (batch_size,)
        with self._mysql.transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_mysql_read(cursor)
                cursor.execute(
                    f"SELECT {columns} FROM {spec.name} {where} "
                    f"ORDER BY {cursor_sql} ASC LIMIT %s",
                    params,
                )
                rows = [dict(row) for row in cursor.fetchall()]
        return [
            self._encode_source_row(spec, row, source_timezone=source_timezone)
            for row in rows
        ]

    @classmethod
    def _encode_source_row(
        cls,
        spec: TableTransferSpec,
        row: dict[str, Any],
        *,
        source_timezone: str,
    ) -> dict[str, Any]:
        encoded = {column: row.get(column) for column in spec.columns}
        for column in spec.non_null_default_columns:
            if encoded[column] is None:
                raise ProjectCatalogTransferSafetyError(
                    f"source column {spec.name}.{column} is null but target is not nullable"
                )
        for column in spec.boolean_columns:
            value = encoded[column]
            encoded[column] = None if value is None else bool(value)
        for column in spec.fixed_char_columns:
            value = encoded[column]
            if isinstance(value, str):
                encoded[column] = value.rstrip(" ")
        source_zone = ZoneInfo(source_timezone)
        for column in spec.datetime_columns:
            value = encoded[column]
            if value is None:
                continue
            if isinstance(value, str):
                normalized_value = value.replace("Z", "+00:00")
                if normalized_value.endswith(("+00", "-00")):
                    normalized_value = f"{normalized_value}:00"
                fraction = re.search(r"\.(\d+)(?=[+-]\d{2}:\d{2}$|$)", normalized_value)
                if fraction and len(fraction.group(1)) < 6:
                    normalized_value = (
                        normalized_value[: fraction.start(1)]
                        + fraction.group(1).ljust(6, "0")
                        + normalized_value[fraction.end(1) :]
                    )
                value = datetime.fromisoformat(normalized_value)
            if not isinstance(value, datetime):
                raise ProjectCatalogTransferSafetyError(
                    f"source column {spec.name}.{column} is not a datetime"
                )
            if value.tzinfo is None:
                value = value.replace(tzinfo=source_zone)
            encoded[column] = value.astimezone(timezone.utc)
        return encoded

    @staticmethod
    def _cursor_from_row(
        spec: TableTransferSpec, row: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {column: row[column] for column in spec.cursor_columns}

    def _read_candidate_batch(
        self, *, after_repo_id: str, batch_size: int
    ) -> list[dict[str, Any]]:
        columns = ", ".join(CANDIDATE_COLUMNS)
        where = "WHERE repo_id > %s" if after_repo_id else ""
        params: tuple[Any, ...] = (after_repo_id, batch_size) if after_repo_id else (batch_size,)
        with self._mysql.transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_mysql_read(cursor)
                cursor.execute(
                    f"SELECT {columns} FROM {CANDIDATE_TABLE} "
                    f"{where} ORDER BY repo_id ASC LIMIT %s",
                    params,
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _begin_mysql_read(cursor: Any) -> None:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        cursor.execute("SET TRANSACTION READ ONLY")

    def _ensure_catalog_run_and_checkpoints(
        self,
        connection: Any,
        *,
        job_id: str,
        target: TargetIdentity,
        options: dict[str, Any],
    ) -> dict[str, TableCheckpoint]:
        source_identity = source_identity_sha256(self._config)
        options_json = json.dumps(options, sort_keys=True, separators=(",", ":"))
        checkpoints: dict[str, TableCheckpoint] = {}
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT source_identity_sha256, target_database, target_schema,
                           schema_version, options_json, status
                    FROM project_catalog_migration_runs
                    WHERE job_id = %s
                    """,
                    (job_id,),
                )
                run = cursor.fetchone()
                if run is None:
                    cursor.execute(
                        """
                        INSERT INTO project_catalog_migration_runs
                            (job_id, source_identity_sha256, target_database,
                             target_schema, schema_version, mode, options_json, status)
                        VALUES (%s, %s, %s, %s, %s, 'load', %s::jsonb, 'running')
                        """,
                        (
                            job_id,
                            source_identity,
                            target.database,
                            target.schema,
                            target.schema_version,
                            options_json,
                        ),
                    )
                else:
                    if str(_row_value(run, "status", 5)) == "completed":
                        raise ProjectCatalogTransferSafetyError(
                            "completed migration job IDs are immutable; use a new job ID"
                        )
                    stored_options = _row_value(run, "options_json", 4)
                    if isinstance(stored_options, str):
                        stored_options = json.loads(stored_options)
                    expected = (
                        source_identity,
                        target.database,
                        target.schema,
                        target.schema_version,
                        options,
                    )
                    actual = (
                        str(_row_value(run, "source_identity_sha256", 0)),
                        str(_row_value(run, "target_database", 1)),
                        str(_row_value(run, "target_schema", 2)),
                        int(_row_value(run, "schema_version", 3)),
                        stored_options,
                    )
                    if actual != expected:
                        raise ProjectCatalogTransferSafetyError(
                            "migration resume options or source/target identity changed"
                        )
                    cursor.execute(
                        """
                        UPDATE project_catalog_migration_runs
                        SET status = 'running', updated_at = CURRENT_TIMESTAMP,
                            completed_at = NULL, last_error_code = NULL,
                            last_error_summary = NULL
                        WHERE job_id = %s
                        """,
                        (job_id,),
                    )
                for spec in TABLE_TRANSFER_SPECS:
                    cursor.execute(
                        """
                        INSERT INTO project_catalog_migration_checkpoints
                            (job_id, table_name, status)
                        VALUES (%s, %s, 'pending')
                        ON CONFLICT (job_id, table_name) DO NOTHING
                        """,
                        (job_id, spec.name),
                    )
                cursor.execute(
                    """
                    SELECT table_name, cursor_json, rows_processed,
                           batches_processed, status, source_prefix_digest_sha256
                    FROM project_catalog_migration_checkpoints
                    WHERE job_id = %s
                    """,
                    (job_id,),
                )
                rows = cursor.fetchall()
        for row in rows:
            table_name = str(_row_value(row, "table_name", 0))
            cursor_json = _row_value(row, "cursor_json", 1) or {}
            if isinstance(cursor_json, str):
                cursor_json = json.loads(cursor_json)
            checkpoints[table_name] = TableCheckpoint(
                cursor=dict(cursor_json),
                rows_processed=int(_row_value(row, "rows_processed", 2) or 0),
                batches_processed=int(_row_value(row, "batches_processed", 3) or 0),
                status=str(_row_value(row, "status", 4) or "pending"),
                source_prefix_digest=str(
                    _row_value(row, "source_prefix_digest_sha256", 5) or "0" * 64
                ),
            )
        missing = {spec.name for spec in TABLE_TRANSFER_SPECS} - checkpoints.keys()
        if missing:
            raise ProjectCatalogTransferSafetyError(
                "catalog transfer checkpoint initialization is incomplete"
            )
        return checkpoints

    def _write_table_batch(
        self,
        connection: Any,
        *,
        spec: TableTransferSpec,
        job_id: str,
        checkpoint: TableCheckpoint,
        rows: list[dict[str, Any]],
    ) -> TableCheckpoint:
        next_cursor = self._cursor_from_row(spec, rows[-1])
        digest = table_batch_digest(spec, rows)
        prefix_digest = extend_table_prefix_digest(
            checkpoint.source_prefix_digest, spec, rows
        )
        placeholders = ", ".join(["%s"] * len(spec.columns))
        columns = ", ".join(spec.columns)
        conflict_columns = ", ".join(spec.conflict_columns)
        updates = ", ".join(
            f"{column} = EXCLUDED.{column}"
            for column in spec.columns
            if column not in spec.conflict_columns
        )
        conflict_action = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
        with connection.transaction():
            with connection.cursor() as cursor:
                if spec is CANDIDATE_SPEC:
                    names = [str(row["full_name"]).lower() for row in rows]
                    cursor.execute(
                        """
                        SELECT repo_id, full_name
                        FROM github_repo_candidates
                        WHERE LOWER(full_name) = ANY(%s)
                        """,
                        (names,),
                    )
                    existing = {
                        str(_row_value(row, "full_name", 1)).lower(): str(
                            _row_value(row, "repo_id", 0)
                        )
                        for row in cursor.fetchall()
                    }
                    for row in rows:
                        target_repo_id = existing.get(str(row["full_name"]).lower())
                        if target_repo_id is not None and target_repo_id != str(row["repo_id"]):
                            raise ProjectCatalogTransferCollisionError(
                                "case-insensitive full_name collision maps to a different repo_id"
                            )
                cursor.executemany(
                    f"INSERT INTO {spec.name} ({columns}) VALUES ({placeholders}) "
                    f"ON CONFLICT ({conflict_columns}) {conflict_action}",
                    [tuple(row.get(column) for column in spec.columns) for row in rows],
                )
                cursor.execute(
                    """
                    UPDATE project_catalog_migration_checkpoints
                    SET cursor_json = %s::jsonb,
                        rows_processed = rows_processed + %s,
                        batches_processed = batches_processed + 1,
                        last_batch_rows = %s,
                        last_batch_digest_sha256 = %s,
                        source_prefix_digest_sha256 = %s,
                        status = 'running', updated_at = CURRENT_TIMESTAMP
                    WHERE job_id = %s AND table_name = %s
                    """,
                    (
                        json.dumps(next_cursor, separators=(",", ":"), default=str),
                        len(rows),
                        len(rows),
                        digest,
                        prefix_digest,
                        job_id,
                        spec.name,
                    ),
                )
        return TableCheckpoint(
            cursor=next_cursor,
            rows_processed=checkpoint.rows_processed + len(rows),
            batches_processed=checkpoint.batches_processed + 1,
            status="running",
            source_prefix_digest=prefix_digest,
        )

    def _source_table_prefix_digest(
        self,
        spec: TableTransferSpec,
        through: Mapping[str, Any],
        batch_size: int,
        source_timezone: str,
    ) -> str:
        prefix = "0" * 64
        after: dict[str, Any] = {}
        while True:
            rows = self._read_table_batch(
                spec,
                after=after,
                batch_size=batch_size,
                source_timezone=source_timezone,
            )
            rows = [
                row
                for row in rows
                if tuple(row[column] for column in spec.cursor_columns)
                <= tuple(through[column] for column in spec.cursor_columns)
            ]
            if not rows:
                break
            prefix = extend_table_prefix_digest(prefix, spec, rows)
            after = self._cursor_from_row(spec, rows[-1])
            if after == dict(through):
                break
        return prefix

    @staticmethod
    def _repair_identity_sequences(connection: Any) -> list[dict[str, Any]]:
        repairs: list[dict[str, Any]] = []
        with connection.transaction():
            with connection.cursor() as cursor:
                for spec in TABLE_TRANSFER_SPECS:
                    if spec.identity_column is None:
                        continue
                    cursor.execute(
                        "SELECT pg_get_serial_sequence(%s, %s) AS sequence_name",
                        (spec.name, spec.identity_column),
                    )
                    sequence_row = cursor.fetchone()
                    sequence_name = _row_value(sequence_row, "sequence_name", 0)
                    if not sequence_name:
                        raise ProjectCatalogTransferSafetyError(
                            f"identity sequence is missing for {spec.name}.{spec.identity_column}"
                        )
                    cursor.execute(
                        f"SELECT MAX({spec.identity_column}) AS maximum_id FROM {spec.name}"
                    )
                    maximum_row = cursor.fetchone()
                    maximum_id = _row_value(maximum_row, "maximum_id", 0)
                    if maximum_id is None:
                        cursor.execute("SELECT setval(%s, 1, false)", (sequence_name,))
                        repairs.append(
                            {"table": spec.name, "maximum_id": None, "is_called": False}
                        )
                    else:
                        cursor.execute(
                            "SELECT setval(%s, %s, true)",
                            (sequence_name, int(maximum_id)),
                        )
                        repairs.append(
                            {
                                "table": spec.name,
                                "maximum_id": int(maximum_id),
                                "is_called": True,
                            }
                        )
        return repairs

    @staticmethod
    def _mark_table_completed(connection: Any, job_id: str, table_name: str) -> None:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE project_catalog_migration_checkpoints
                    SET status = 'completed', last_batch_rows = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE job_id = %s AND table_name = %s
                    """,
                    (job_id, table_name),
                )

    @staticmethod
    def _mark_catalog_completed(connection: Any, job_id: str) -> None:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE project_catalog_migration_runs
                    SET status = 'completed', updated_at = CURRENT_TIMESTAMP,
                        completed_at = CURRENT_TIMESTAMP
                    WHERE job_id = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM project_catalog_migration_checkpoints
                          WHERE job_id = %s AND status <> 'completed'
                      )
                    """,
                    (job_id, job_id),
                )

    def _record_catalog_failure_best_effort(
        self,
        *,
        job_id: str,
        attempt: int,
        error: BaseException,
        retryable: bool,
    ) -> None:
        sqlstate = str(getattr(error, "sqlstate", "") or "") or None
        error_class = type(error).__name__[:128]
        summary = "catalog transfer failed; inspect database logs"
        try:
            with self._postgres.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO project_catalog_migration_failures
                            (job_id, table_name, cursor_json, attempt, sqlstate,
                             error_class, error_summary, retryable)
                        SELECT %s, c.table_name, c.cursor_json, %s, %s, %s, %s, %s
                        FROM project_catalog_migration_checkpoints c
                        WHERE c.job_id = %s AND c.status = 'running'
                        """,
                        (
                            job_id,
                            attempt,
                            sqlstate,
                            error_class,
                            summary,
                            retryable,
                            job_id,
                        ),
                    )
                    cursor.execute(
                        """
                        UPDATE project_catalog_migration_checkpoints
                        SET status = 'failed', updated_at = CURRENT_TIMESTAMP
                        WHERE job_id = %s AND status = 'running'
                        """,
                        (job_id,),
                    )
                    cursor.execute(
                        """
                        UPDATE project_catalog_migration_runs
                        SET status = 'failed', updated_at = CURRENT_TIMESTAMP,
                            last_error_code = %s, last_error_summary = %s
                        WHERE job_id = %s
                        """,
                        (sqlstate or error_class, summary, job_id),
                    )
        except BaseException:
            pass

    @staticmethod
    def _validate_source_timezone(source_timezone: str) -> str:
        value = str(source_timezone or "").strip()
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ProjectCatalogTransferSafetyError(
                "source timezone must be a valid IANA timezone"
            ) from error
        return value

    def _ensure_run_and_checkpoint(
        self,
        connection: Any,
        *,
        job_id: str,
        target: TargetIdentity,
        options: dict[str, Any],
    ) -> CandidateCheckpoint:
        source_identity = source_identity_sha256(self._config)
        options_json = json.dumps(options, sort_keys=True, separators=(",", ":"))
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT source_identity_sha256, target_database, target_schema,
                           schema_version, options_json, status
                    FROM project_catalog_migration_runs
                    WHERE job_id = %s
                    """,
                    (job_id,),
                )
                run = cursor.fetchone()
                if run is None:
                    cursor.execute(
                        """
                        INSERT INTO project_catalog_migration_runs
                            (job_id, source_identity_sha256, target_database,
                             target_schema, schema_version, mode, options_json, status)
                        VALUES (%s, %s, %s, %s, %s, 'load', %s::jsonb, 'running')
                        """,
                        (
                            job_id,
                            source_identity,
                            target.database,
                            target.schema,
                            target.schema_version,
                            options_json,
                        ),
                    )
                else:
                    if str(_row_value(run, "status", 5)) == "completed":
                        raise ProjectCatalogTransferSafetyError(
                            "completed migration job IDs are immutable; use a new job ID"
                        )
                    stored_options = _row_value(run, "options_json", 4)
                    if isinstance(stored_options, str):
                        stored_options = json.loads(stored_options)
                    expected = (
                        source_identity,
                        target.database,
                        target.schema,
                        target.schema_version,
                        options,
                    )
                    actual = (
                        str(_row_value(run, "source_identity_sha256", 0)),
                        str(_row_value(run, "target_database", 1)),
                        str(_row_value(run, "target_schema", 2)),
                        int(_row_value(run, "schema_version", 3)),
                        stored_options,
                    )
                    if actual != expected:
                        raise ProjectCatalogTransferSafetyError(
                            "migration resume options or source/target identity changed"
                        )
                    cursor.execute(
                        """
                        UPDATE project_catalog_migration_runs
                        SET status = 'running', updated_at = CURRENT_TIMESTAMP,
                            completed_at = NULL, last_error_code = NULL,
                            last_error_summary = NULL
                        WHERE job_id = %s
                        """,
                        (job_id,),
                    )
                cursor.execute(
                    """
                    INSERT INTO project_catalog_migration_checkpoints
                        (job_id, table_name, status)
                    VALUES (%s, %s, 'running')
                    ON CONFLICT (job_id, table_name) DO UPDATE
                    SET status = 'running', updated_at = CURRENT_TIMESTAMP
                    RETURNING cursor_json, rows_processed, batches_processed, status,
                              source_prefix_digest_sha256
                    """,
                    (job_id, CANDIDATE_TABLE),
                )
                checkpoint_row = cursor.fetchone()
        cursor_json = _row_value(checkpoint_row, "cursor_json", 0) or {}
        if isinstance(cursor_json, str):
            cursor_json = json.loads(cursor_json)
        status = str(_row_value(checkpoint_row, "status", 3))
        if status == "completed":
            raise ProjectCatalogTransferSafetyError(
                "completed migration job IDs are immutable; use a new job ID"
            )
        return CandidateCheckpoint(
            cursor=str(cursor_json.get("repo_id") or ""),
            rows_processed=int(_row_value(checkpoint_row, "rows_processed", 1) or 0),
            batches_processed=int(_row_value(checkpoint_row, "batches_processed", 2) or 0),
            status=status,
            source_prefix_digest=str(
                _row_value(checkpoint_row, "source_prefix_digest_sha256", 4)
                or "0" * 64
            ),
        )

    def _write_candidate_batch(
        self,
        connection: Any,
        *,
        job_id: str,
        checkpoint: CandidateCheckpoint,
        rows: list[dict[str, Any]],
    ) -> CandidateCheckpoint:
        last_repo_id = str(rows[-1]["repo_id"])
        digest = candidate_batch_digest(rows)
        prefix_digest = extend_prefix_digest(
            checkpoint.source_prefix_digest, rows
        )
        placeholders = ", ".join(["%s"] * len(CANDIDATE_COLUMNS))
        columns = ", ".join(CANDIDATE_COLUMNS)
        updates = ", ".join(
            f"{column} = EXCLUDED.{column}"
            for column in CANDIDATE_COLUMNS
            if column != "repo_id"
        )
        with connection.transaction():
            with connection.cursor() as cursor:
                names = [str(row["full_name"]).lower() for row in rows]
                cursor.execute(
                    """
                    SELECT repo_id, full_name
                    FROM github_repo_candidates
                    WHERE LOWER(full_name) = ANY(%s)
                    """,
                    (names,),
                )
                existing = {
                    str(_row_value(row, "full_name", 1)).lower(): str(
                        _row_value(row, "repo_id", 0)
                    )
                    for row in cursor.fetchall()
                }
                for row in rows:
                    target_repo_id = existing.get(str(row["full_name"]).lower())
                    if target_repo_id is not None and target_repo_id != str(row["repo_id"]):
                        raise ProjectCatalogTransferCollisionError(
                            "case-insensitive full_name collision maps to a different repo_id"
                        )
                cursor.executemany(
                    f"INSERT INTO {CANDIDATE_TABLE} ({columns}) VALUES ({placeholders}) "
                    f"ON CONFLICT (repo_id) DO UPDATE SET {updates}",
                    [tuple(row.get(column) for column in CANDIDATE_COLUMNS) for row in rows],
                )
                cursor.execute(
                    """
                    UPDATE project_catalog_migration_checkpoints
                    SET cursor_json = %s::jsonb,
                        rows_processed = rows_processed + %s,
                        batches_processed = batches_processed + 1,
                        last_batch_rows = %s,
                        last_batch_digest_sha256 = %s,
                        source_prefix_digest_sha256 = %s,
                        status = 'running', updated_at = CURRENT_TIMESTAMP
                    WHERE job_id = %s AND table_name = %s
                    """,
                    (
                        json.dumps({"repo_id": last_repo_id}, separators=(",", ":")),
                        len(rows),
                        len(rows),
                        digest,
                        prefix_digest,
                        job_id,
                        CANDIDATE_TABLE,
                    ),
                )
        return CandidateCheckpoint(
            cursor=last_repo_id,
            rows_processed=checkpoint.rows_processed + len(rows),
            batches_processed=checkpoint.batches_processed + 1,
            status="running",
            source_prefix_digest=prefix_digest,
        )

    def _record_failure_best_effort(
        self,
        *,
        job_id: str,
        attempt: int,
        error: BaseException,
        retryable: bool,
    ) -> None:
        sqlstate = str(getattr(error, "sqlstate", "") or "") or None
        error_class = type(error).__name__[:128]
        summary = "catalog transfer failed; inspect database logs"
        try:
            with self._postgres.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO project_catalog_migration_failures
                            (job_id, table_name, cursor_json, attempt, sqlstate,
                             error_class, error_summary, retryable)
                        SELECT %s, %s, c.cursor_json, %s, %s, %s, %s, %s
                        FROM project_catalog_migration_checkpoints c
                        WHERE c.job_id = %s AND c.table_name = %s
                        """,
                        (
                            job_id,
                            CANDIDATE_TABLE,
                            attempt,
                            sqlstate,
                            error_class,
                            summary,
                            retryable,
                            job_id,
                            CANDIDATE_TABLE,
                        ),
                    )
                    cursor.execute(
                        """
                        UPDATE project_catalog_migration_checkpoints
                        SET status = 'failed', updated_at = CURRENT_TIMESTAMP
                        WHERE job_id = %s AND table_name = %s
                        """,
                        (job_id, CANDIDATE_TABLE),
                    )
                    cursor.execute(
                        """
                        UPDATE project_catalog_migration_runs
                        SET status = 'failed', updated_at = CURRENT_TIMESTAMP,
                            last_error_code = %s, last_error_summary = %s
                        WHERE job_id = %s
                        """,
                        (sqlstate or error_class, summary, job_id),
                    )
        except BaseException:
            pass

    @staticmethod
    def _mark_completed(connection: Any, job_id: str) -> None:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE project_catalog_migration_checkpoints
                    SET status = 'completed', last_batch_rows = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE job_id = %s AND table_name = %s
                    """,
                    (job_id, CANDIDATE_TABLE),
                )
                cursor.execute(
                    """
                    UPDATE project_catalog_migration_runs
                    SET status = 'completed', updated_at = CURRENT_TIMESTAMP,
                        completed_at = CURRENT_TIMESTAMP
                    WHERE job_id = %s
                    """,
                    (job_id,),
                )

    @staticmethod
    def _acquire_lock(connection: Any, lock_id: int) -> None:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (lock_id,))
                row = cursor.fetchone()
        if not bool(_row_value(row, "acquired", 0)):
            raise ProjectCatalogTransferSafetyError(
                "another transfer process already owns this job/table"
            )

    @staticmethod
    def _release_lock(connection: Any, lock_id: int) -> None:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))

    def _source_candidate_prefix_digest(
        self, through_repo_id: str, batch_size: int
    ) -> str:
        prefix = "0" * 64
        after = ""
        columns = ", ".join(CANDIDATE_COLUMNS)
        while True:
            with self._mysql.transaction() as connection:
                with connection.cursor() as cursor:
                    self._begin_mysql_read(cursor)
                    cursor.execute(
                        f"SELECT {columns} FROM {CANDIDATE_TABLE} "
                        "WHERE repo_id > %s AND repo_id <= %s "
                        "ORDER BY repo_id ASC LIMIT %s",
                        (after, through_repo_id, batch_size),
                    )
                    rows = [dict(row) for row in cursor.fetchall()]
            if not rows:
                break
            prefix = extend_prefix_digest(prefix, rows)
            after = str(rows[-1]["repo_id"])
        return prefix

    def _digest_source_candidates(self, batch_size: int) -> tuple[int, str]:
        return self._digest_candidates(self._read_candidate_batch, batch_size)

    def _digest_target_candidates(self, batch_size: int) -> tuple[int, str]:
        def read_target(*, after_repo_id: str, batch_size: int) -> list[dict[str, Any]]:
            columns = ", ".join(CANDIDATE_COLUMNS)
            where = "WHERE repo_id > %s" if after_repo_id else ""
            params: tuple[Any, ...] = (
                (after_repo_id, batch_size) if after_repo_id else (batch_size,)
            )
            with self._postgres.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"SELECT {columns} FROM {CANDIDATE_TABLE} "
                        f"{where} ORDER BY repo_id ASC LIMIT %s",
                        params,
                    )
                    rows = cursor.fetchall()
            return [dict(row) for row in rows]

        return self._digest_candidates(read_target, batch_size)

    @staticmethod
    def _digest_candidates(
        reader: Callable[..., list[dict[str, Any]]], batch_size: int
    ) -> tuple[int, str]:
        digest = hashlib.sha256()
        count = 0
        after = ""
        while True:
            rows = reader(after_repo_id=after, batch_size=batch_size)
            if not rows:
                break
            for row in rows:
                encoded = bytes.fromhex(candidate_batch_digest([row]))
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
            count += len(rows)
            after = str(rows[-1]["repo_id"])
        return count, digest.hexdigest()

    def _validate_production_authorization(self, cli_authorized: bool) -> None:
        environment = str(getattr(self._config, "env", "development") or "").lower()
        env_authorized = os.getenv(
            "PROJECT_CATALOG_MIGRATION_PRODUCTION_AUTHORIZED", ""
        ).strip().lower() in {"1", "true", "yes"}
        if environment == "production" and not (cli_authorized and env_authorized):
            raise ProjectCatalogTransferSafetyError(
                "production migration requires independent CLI and environment authorization"
            )

    @staticmethod
    def _validate_job_id(job_id: str) -> str:
        value = str(job_id or "").strip()
        if not value or len(value) > 128:
            raise ProjectCatalogTransferSafetyError(
                "job ID is required and must be at most 128 characters"
            )
        return value

    @staticmethod
    def _validate_batch_size(batch_size: int) -> int:
        value = int(batch_size)
        if value < 1 or value > MAX_BATCH_SIZE:
            raise ProjectCatalogTransferSafetyError(
                f"batch size must be between 1 and {MAX_BATCH_SIZE}"
            )
        return value
