from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from backend.app.core.config import settings
from backend.app.core.database import DatabaseLifecycle, mysql_database
from backend.app.core.postgres_database import PostgresDatabaseLifecycle, postgres_database
from backend.app.services.project_catalog_transfer import (
    TABLE_TRANSFER_SPEC_BY_NAME,
    ProjectCatalogTransferService,
    ProjectCatalogTransferSafetyError,
    TableTransferSpec,
)


class ProjectCatalogSyncError(RuntimeError):
    """Raised when durable project-catalog replay cannot continue safely."""


class ProjectCatalogSyncPermanentError(ProjectCatalogSyncError):
    """Raised for malformed or incompatible events that must not be retried."""


@dataclass(frozen=True)
class OutboxEvent:
    id: int
    event_id: str
    aggregate_type: str
    aggregate_key: dict[str, Any]
    operation: str
    source_method: str
    attempt_count: int
    lease_token: str


@dataclass(frozen=True)
class SyncBatchResult:
    claimed: int
    processed: int
    retried: int
    dead: int


class ProjectCatalogReconciliationWriter:
    """Apply one authoritative MySQL row and event marker atomically."""

    def __init__(
        self,
        mysql: DatabaseLifecycle = mysql_database,
        postgres: PostgresDatabaseLifecycle = postgres_database,
        *,
        source_timezone: str = "UTC",
    ) -> None:
        self._mysql = mysql
        self._postgres = postgres
        self._source_timezone = source_timezone

    def apply(self, event: OutboxEvent) -> None:
        spec = self._spec(event.aggregate_type)
        key_columns = self._key_columns(spec, event.aggregate_key)
        aggregate_key_json = json.dumps(
            event.aggregate_key,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        lock_id = self._aggregate_lock_id(event.aggregate_type, aggregate_key_json)
        with self._postgres.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", (lock_id,))
                cursor.execute(
                    """
                    INSERT INTO project_catalog_applied_events (
                        event_id, outbox_id, aggregate_type, aggregate_key,
                        operation, source_method
                    ) VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING event_id
                    """,
                    (
                        event.event_id,
                        event.id,
                        event.aggregate_type,
                        aggregate_key_json,
                        event.operation,
                        event.source_method,
                    ),
                )
                if cursor.fetchone() is None:
                    return
                row = self._read_source_row(spec, event.aggregate_key)
                if row is None:
                    self._delete_target_row(cursor, spec, event.aggregate_key)
                else:
                    self._upsert_target_row(cursor, spec, row, key_columns)

    @staticmethod
    def _aggregate_lock_id(aggregate_type: str, aggregate_key_json: str) -> int:
        payload = (
            f"aigcnews:project-catalog-sync:{aggregate_type}:{aggregate_key_json}"
        ).encode("utf-8")
        return int.from_bytes(
            hashlib.sha256(payload).digest()[:8],
            "big",
            signed=True,
        )

    @staticmethod
    def _spec(aggregate_type: str) -> TableTransferSpec:
        spec = TABLE_TRANSFER_SPEC_BY_NAME.get(aggregate_type)
        if spec is None:
            raise ProjectCatalogSyncPermanentError("unknown project catalog aggregate type")
        return spec

    def _read_source_row(
        self,
        spec: TableTransferSpec,
        aggregate_key: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        key_columns = self._key_columns(spec, aggregate_key)
        columns = ", ".join(f"`{column}`" for column in spec.columns)
        predicate = " AND ".join(f"`{column}` = %s" for column in key_columns)
        params = tuple(aggregate_key[column] for column in key_columns)
        with self._mysql.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    f"SELECT {columns} FROM `{spec.name}` WHERE {predicate} LIMIT 1",
                    params,
                )
                source = cursor.fetchone()
        if source is None:
            return None
        try:
            return ProjectCatalogTransferService._encode_source_row(
                spec,
                dict(source),
                source_timezone=self._source_timezone,
            )
        except (ProjectCatalogTransferSafetyError, ValueError) as exc:
            raise ProjectCatalogSyncPermanentError("source row cannot be encoded") from exc

    @staticmethod
    def _key_columns(
        spec: TableTransferSpec,
        aggregate_key: Mapping[str, Any],
    ) -> tuple[str, ...]:
        candidates = (spec.cursor_columns, spec.natural_key_columns)
        for columns in candidates:
            if columns and set(columns) == set(aggregate_key):
                return columns
        raise ProjectCatalogSyncPermanentError("aggregate key does not match table identity")

    @classmethod
    def _delete_target_row(
        cls,
        cursor: Any,
        spec: TableTransferSpec,
        aggregate_key: Mapping[str, Any],
    ) -> None:
        key_columns = cls._key_columns(spec, aggregate_key)
        predicate = " AND ".join(f"{column} = %s" for column in key_columns)
        cursor.execute(
            f"DELETE FROM {spec.name} WHERE {predicate}",
            tuple(aggregate_key[column] for column in key_columns),
        )

    @staticmethod
    def _upsert_target_row(
        cursor: Any,
        spec: TableTransferSpec,
        row: Mapping[str, Any],
        key_columns: tuple[str, ...] | None = None,
    ) -> None:
        key_columns = key_columns or spec.conflict_columns
        columns = ", ".join(spec.columns)
        placeholders = ", ".join(["%s"] * len(spec.columns))
        conflict_columns = ", ".join(key_columns)
        updates = ", ".join(
            f"{column} = EXCLUDED.{column}"
            for column in spec.columns
            if column not in key_columns
        )
        action = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
        cursor.execute(
            f"INSERT INTO {spec.name} ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_columns}) {action}",
            tuple(row.get(column) for column in spec.columns),
        )


class ProjectCatalogSyncWorker:
    """Lease MySQL events, replay outside the lease transaction, then fenced-ack."""

    def __init__(
        self,
        mysql: DatabaseLifecycle = mysql_database,
        writer: ProjectCatalogReconciliationWriter | None = None,
        *,
        batch_size: int | None = None,
        lease_seconds: int | None = None,
        max_attempts: int | None = None,
    ) -> None:
        self._mysql = mysql
        self._writer = writer or ProjectCatalogReconciliationWriter(mysql=mysql)
        self._batch_size = max(1, int(batch_size or settings.project_catalog_sync_batch_size))
        self._lease_seconds = max(1, int(lease_seconds or settings.project_catalog_sync_lease_seconds))
        self._max_attempts = max(1, int(max_attempts or settings.project_catalog_sync_max_attempts))

    def run_once(self) -> SyncBatchResult:
        events = self.claim()
        processed = retried = dead = 0
        for event in events:
            try:
                self._writer.apply(event)
            except ProjectCatalogSyncPermanentError as exc:
                self._fail(event, exc, permanent=True)
                dead += 1
            except Exception as exc:
                is_dead = event.attempt_count >= self._max_attempts
                self._fail(event, exc, permanent=is_dead)
                if is_dead:
                    dead += 1
                else:
                    retried += 1
            else:
                self._ack(event)
                processed += 1
        return SyncBatchResult(len(events), processed, retried, dead)

    def claim(self) -> list[OutboxEvent]:
        lease_token = str(uuid.uuid4())
        with self._mysql.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM project_catalog_outbox
                    WHERE (
                        status IN ('pending', 'retry') AND available_at <= UTC_TIMESTAMP(6)
                    ) OR (
                        status = 'leased' AND lease_expires_at <= UTC_TIMESTAMP(6)
                    )
                    ORDER BY id
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                    """,
                    (self._batch_size,),
                )
                ids = [int(row["id"]) for row in cursor.fetchall()]
                if not ids:
                    return []
                placeholders = ", ".join(["%s"] * len(ids))
                cursor.execute(
                    f"""
                    UPDATE project_catalog_outbox
                    SET status = 'leased', lease_token = %s,
                        lease_expires_at = DATE_ADD(UTC_TIMESTAMP(6), INTERVAL %s SECOND),
                        attempt_count = attempt_count + 1
                    WHERE id IN ({placeholders})
                    """,
                    (lease_token, self._lease_seconds, *ids),
                )
                cursor.execute(
                    f"""
                    SELECT id, event_id, aggregate_type, aggregate_key, operation,
                           source_method, attempt_count, lease_token
                    FROM project_catalog_outbox
                    WHERE id IN ({placeholders}) AND lease_token = %s
                    ORDER BY id
                    """,
                    (*ids, lease_token),
                )
                rows = cursor.fetchall()
        events: list[OutboxEvent] = []
        for row in rows:
            try:
                events.append(self._event(row))
            except ProjectCatalogSyncPermanentError:
                self._dead_malformed_row(row)
        return events

    @staticmethod
    def _event(row: Mapping[str, Any]) -> OutboxEvent:
        try:
            aggregate_key = json.loads(str(row["aggregate_key"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProjectCatalogSyncPermanentError("outbox aggregate key is invalid") from exc
        if not isinstance(aggregate_key, dict):
            raise ProjectCatalogSyncPermanentError("outbox aggregate key must be an object")
        try:
            event_id = str(uuid.UUID(str(row["event_id"])))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ProjectCatalogSyncPermanentError("outbox event ID is invalid") from exc
        operation = str(row["operation"])
        if operation not in {"reconcile", "delete"}:
            raise ProjectCatalogSyncPermanentError("outbox operation is invalid")
        return OutboxEvent(
            id=int(row["id"]),
            event_id=event_id,
            aggregate_type=str(row["aggregate_type"]),
            aggregate_key=aggregate_key,
            operation=operation,
            source_method=str(row["source_method"]),
            attempt_count=int(row["attempt_count"]),
            lease_token=str(row["lease_token"]),
        )

    def _dead_malformed_row(self, row: Mapping[str, Any]) -> None:
        outbox_id = int(row["id"])
        lease_token = str(row["lease_token"])
        with self._mysql.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE project_catalog_outbox
                    SET status = 'dead', lease_token = NULL, lease_expires_at = NULL,
                        last_error_code = 'ProjectCatalogSyncPermanentError',
                        last_error_summary = 'invalid durable outbox payload'
                    WHERE id = %s AND status = 'leased' AND lease_token = %s
                    """,
                    (outbox_id, lease_token),
                )
                if cursor.rowcount != 1:
                    raise ProjectCatalogSyncError(
                        "malformed outbox row lost its lease fence"
                    )

    def _ack(self, event: OutboxEvent) -> None:
        with self._mysql.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE project_catalog_outbox
                    SET status = 'processed', processed_at = UTC_TIMESTAMP(6),
                        lease_token = NULL, lease_expires_at = NULL,
                        last_error_code = NULL, last_error_summary = NULL
                    WHERE id = %s AND status = 'leased' AND lease_token = %s
                    """,
                    (event.id, event.lease_token),
                )
                if cursor.rowcount != 1:
                    raise ProjectCatalogSyncError("outbox acknowledgement lost its lease fence")

    def _fail(self, event: OutboxEvent, exc: Exception, *, permanent: bool) -> None:
        status = "dead" if permanent else "retry"
        delay_seconds = min(3600, 2 ** min(event.attempt_count, 12))
        error_code = type(exc).__name__[:128]
        error_summary = "permanent replay failure" if permanent else "transient replay failure"
        with self._mysql.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE project_catalog_outbox
                    SET status = %s,
                        available_at = DATE_ADD(UTC_TIMESTAMP(6), INTERVAL %s SECOND),
                        lease_token = NULL, lease_expires_at = NULL,
                        last_error_code = %s, last_error_summary = %s
                    WHERE id = %s AND status = 'leased' AND lease_token = %s
                    """,
                    (
                        status,
                        delay_seconds,
                        error_code,
                        error_summary,
                        event.id,
                        event.lease_token,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ProjectCatalogSyncError("outbox failure update lost its lease fence")

    def status(self) -> dict[str, Any]:
        with self._mysql.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        SUM(status = 'pending') AS pending,
                        SUM(status = 'leased') AS leased,
                        SUM(status = 'retry') AS retry,
                        SUM(status = 'dead') AS dead,
                        MAX(CASE WHEN status = 'processed' THEN id END) AS high_water,
                        MIN(CASE WHEN status IN ('pending', 'leased', 'retry') THEN created_at END) AS oldest_pending_at
                    FROM project_catalog_outbox
                    """
                )
                row = cursor.fetchone() or {}
        oldest = row.get("oldest_pending_at")
        if isinstance(oldest, datetime):
            oldest = oldest.replace(tzinfo=oldest.tzinfo or timezone.utc).isoformat()
        return {
            "pending": int(row.get("pending") or 0),
            "leased": int(row.get("leased") or 0),
            "retry": int(row.get("retry") or 0),
            "dead": int(row.get("dead") or 0),
            "high_water": int(row.get("high_water") or 0),
            "oldest_pending_at": oldest,
        }
