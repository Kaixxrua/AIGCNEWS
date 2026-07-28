from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from backend.app.core.database import DatabaseLifecycle, mysql_database
from backend.app.core.postgres_database import PostgresDatabaseLifecycle, postgres_database
from backend.app.services.application_data_transfer import (
    APPLICATION_TABLE_TRANSFER_SPECS,
    ApplicationTableTransferSpec,
)
from backend.app.services.project_catalog_transfer import (
    DEFAULT_BATCH_SIZE,
    MAX_BATCH_SIZE,
    ProjectCatalogTransferSafetyError,
    TargetIdentity,
    _mysql_identifier,
    _row_value,
)


class TransferReconciliationError(RuntimeError):
    """Raised when a completed transfer cannot be reconciled safely."""


def _canonical_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise TransferReconciliationError("invalid JSON encountered during reconciliation") from error
    return value


def _canonical_value(
    spec: ApplicationTableTransferSpec, column: str, value: Any, source_timezone: str
) -> Any:
    if value is None:
        return None
    if column in spec.boolean_columns:
        return bool(value)
    if column in spec.json_columns:
        return _canonical_json(value)
    if column in spec.datetime_columns:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime):
            raise TransferReconciliationError("invalid datetime encountered during reconciliation")
        if value.tzinfo is None:
            from zoneinfo import ZoneInfo

            value = value.replace(tzinfo=ZoneInfo(source_timezone))
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bytes):
        return value.hex()
    return value


def canonical_row_bytes(
    spec: ApplicationTableTransferSpec,
    row: Mapping[str, Any],
    *,
    source_timezone: str = "UTC",
) -> bytes:
    values = [
        _canonical_value(spec, column, row.get(column), source_timezone)
        for column in spec.columns
    ]
    return json.dumps(
        values, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_key_bytes(
    spec: ApplicationTableTransferSpec,
    row: Mapping[str, Any],
    *,
    source_timezone: str = "UTC",
) -> bytes:
    values = [
        _canonical_value(spec, column, row.get(column), source_timezone)
        for column in spec.cursor_columns
    ]
    return json.dumps(
        values, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _extend_digest(digest: Any, payload: bytes) -> None:
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


class TableTransferReconciliationService:
    """Read-only, keyset reconciliation for a completed table transfer."""

    def __init__(
        self,
        *,
        mysql: DatabaseLifecycle = mysql_database,
        postgres: PostgresDatabaseLifecycle = postgres_database,
        table_specs: Sequence[ApplicationTableTransferSpec] = APPLICATION_TABLE_TRANSFER_SPECS,
        minimum_schema_version: int = 6,
        check_foreign_keys: bool = True,
    ) -> None:
        self._mysql = mysql
        self._postgres = postgres
        self._table_specs = tuple(table_specs)
        self._minimum_schema_version = minimum_schema_version
        self._check_foreign_keys = check_foreign_keys

    def verify(
        self,
        *,
        job_id: str,
        target_database: str,
        target_schema: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        source_timezone: str = "UTC",
    ) -> dict[str, Any]:
        if not job_id.strip() or len(job_id) > 128:
            raise ProjectCatalogTransferSafetyError("job ID is required and must be at most 128 characters")
        if batch_size < 1 or batch_size > MAX_BATCH_SIZE:
            raise ProjectCatalogTransferSafetyError(
                f"batch size must be between 1 and {MAX_BATCH_SIZE}"
            )
        with self._postgres.connection() as connection:
            target = self._confirm_target(connection, target_database, target_schema)
            self._require_terminal_checkpoints(connection, job_id)
            tables = []
            for spec in self._table_specs:
                source = self._digest_source(spec, batch_size, source_timezone)
                target_digest = self._digest_target(
                    connection, spec, batch_size, source_timezone
                )
                identity = self._identity_check(connection, spec, source[3], target_digest[3])
                matches = source[:3] == target_digest[:3] and identity["status"] == "match"
                tables.append(
                    {
                        "table": spec.name,
                        "status": "match" if matches else "mismatch",
                        "source_count": source[0],
                        "target_count": target_digest[0],
                        "source_key_digest_sha256": source[1],
                        "target_key_digest_sha256": target_digest[1],
                        "source_row_digest_sha256": source[2],
                        "target_row_digest_sha256": target_digest[2],
                        "identity": identity,
                    }
                )
            foreign_keys = (
                self._foreign_key_checks(
                    connection, {spec.name for spec in self._table_specs}
                )
                if self._check_foreign_keys
                else []
            )
        matched = all(item["status"] == "match" for item in tables) and all(
            item["orphan_count"] == 0 for item in foreign_keys
        )
        return {
            "status": "match" if matched else "mismatch",
            "job_id": job_id,
            "target_database": target.database,
            "target_schema": target.schema,
            "schema_version": target.schema_version,
            "tables": tables,
            "foreign_keys": foreign_keys,
        }

    def _confirm_target(self, connection: Any, database: str, schema: str) -> TargetIdentity:
        if not database.strip() or not schema.strip():
            raise ProjectCatalogTransferSafetyError(
                "target database and schema confirmations are required"
            )
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SELECT current_database() AS database, current_schema() AS schema")
                row = cursor.fetchone()
                cursor.execute("SELECT COALESCE(MAX(version), 0) AS version FROM app_schema_migrations")
                version_row = cursor.fetchone()
        actual_database = str(_row_value(row, "database", 0) or "")
        actual_schema = str(_row_value(row, "schema", 1) or "")
        version = int(_row_value(version_row, "version", 0) or 0)
        if (actual_database, actual_schema) != (database, schema):
            raise ProjectCatalogTransferSafetyError(
                "target database/schema confirmation does not match the active connection"
            )
        if version < self._minimum_schema_version:
            raise ProjectCatalogTransferSafetyError("PostgreSQL schema version is below the required version")
        return TargetIdentity(actual_database, actual_schema, version)

    def _require_terminal_checkpoints(self, connection: Any, job_id: str) -> None:
        expected = {spec.name for spec in self._table_specs}
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    "SELECT status FROM project_catalog_migration_runs WHERE job_id = %s",
                    (job_id,),
                )
                run = cursor.fetchone()
                cursor.execute(
                    "SELECT table_name, status FROM project_catalog_migration_checkpoints WHERE job_id = %s",
                    (job_id,),
                )
                checkpoints = cursor.fetchall()
        statuses = {
            str(_row_value(row, "table_name", 0)): str(_row_value(row, "status", 1))
            for row in checkpoints
        }
        if run is None or str(_row_value(run, "status", 0)) != "completed":
            raise TransferReconciliationError("migration run is not in completed terminal state")
        if set(statuses) != expected or any(status != "completed" for status in statuses.values()):
            raise TransferReconciliationError("migration checkpoints are not all completed")

    def _digest_source(
        self, spec: ApplicationTableTransferSpec, batch_size: int, source_timezone: str
    ) -> tuple[int, str, str, Any]:
        after: dict[str, Any] = {}
        return self._digest_batches(
            spec,
            lambda: self._read_source_batch(spec, after, batch_size),
            after,
            source_timezone,
        )

    def _digest_target(
        self,
        connection: Any,
        spec: ApplicationTableTransferSpec,
        batch_size: int,
        source_timezone: str,
    ) -> tuple[int, str, str, Any]:
        after: dict[str, Any] = {}
        return self._digest_batches(
            spec,
            lambda: self._read_target_batch(connection, spec, after, batch_size),
            after,
            source_timezone,
        )

    @staticmethod
    def _digest_batches(
        spec: ApplicationTableTransferSpec,
        reader: Any,
        after: dict[str, Any],
        source_timezone: str,
    ) -> tuple[int, str, str, Any]:
        key_digest = hashlib.sha256()
        row_digest = hashlib.sha256()
        count = 0
        high_water = None
        while True:
            rows = reader()
            if not rows:
                break
            for row in rows:
                _extend_digest(
                    key_digest,
                    canonical_key_bytes(spec, row, source_timezone=source_timezone),
                )
                _extend_digest(
                    row_digest,
                    canonical_row_bytes(spec, row, source_timezone=source_timezone),
                )
            count += len(rows)
            after.update({column: rows[-1][column] for column in spec.cursor_columns})
            if spec.identity_column:
                high_water = rows[-1][spec.identity_column]
        return count, key_digest.hexdigest(), row_digest.hexdigest(), high_water

    def _read_source_batch(
        self, spec: ApplicationTableTransferSpec, after: Mapping[str, Any], batch_size: int
    ) -> list[dict[str, Any]]:
        columns = ", ".join(_mysql_identifier(column) for column in spec.columns)
        expressions = [
            f"BINARY {_mysql_identifier(column)}" if column in spec.text_cursor_columns else _mysql_identifier(column)
            for column in spec.cursor_columns
        ]
        where = ""
        params: tuple[Any, ...] = (batch_size,)
        if after:
            where = f"WHERE ({', '.join(expressions)}) > ({', '.join(['%s'] * len(expressions))})"
            params = tuple(after[column] for column in spec.cursor_columns) + (batch_size,)
        with self._mysql.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    f"SELECT {columns} FROM {_mysql_identifier(spec.name)} {where} "
                    f"ORDER BY {', '.join(expressions)} ASC LIMIT %s",
                    params,
                )
                return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _read_target_batch(
        connection: Any,
        spec: ApplicationTableTransferSpec,
        after: Mapping[str, Any],
        batch_size: int,
    ) -> list[dict[str, Any]]:
        columns = ", ".join(spec.columns)
        cursors = ", ".join(spec.cursor_columns)
        where = ""
        params: tuple[Any, ...] = (batch_size,)
        if after:
            where = f"WHERE ({cursors}) > ({', '.join(['%s'] * len(spec.cursor_columns))})"
            params = tuple(after[column] for column in spec.cursor_columns) + (batch_size,)
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    f"SELECT {columns} FROM {spec.name} {where} ORDER BY {cursors} ASC LIMIT %s",
                    params,
                )
                return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _identity_check(
        connection: Any,
        spec: ApplicationTableTransferSpec,
        source_high_water: Any,
        target_high_water: Any,
    ) -> dict[str, Any]:
        if spec.identity_column is None:
            return {"status": "not_applicable"}
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SELECT pg_get_serial_sequence(%s, %s) AS sequence_name", (spec.name, spec.identity_column))
                row = cursor.fetchone()
                sequence_name = _row_value(row, "sequence_name", 0)
                if not sequence_name:
                    return {"status": "mismatch", "reason": "missing_sequence"}
                cursor.execute(f"SELECT last_value, is_called FROM {sequence_name}")
                sequence = cursor.fetchone()
        last_value = int(_row_value(sequence, "last_value", 0))
        is_called = bool(_row_value(sequence, "is_called", 1))
        high_water_matches = source_high_water == target_high_water
        sequence_safe = (
            target_high_water is None and last_value == 1 and not is_called
        ) or (
            target_high_water is not None and is_called and last_value >= int(target_high_water)
        )
        return {
            "status": "match" if high_water_matches and sequence_safe else "mismatch",
            "source_high_water": source_high_water,
            "target_high_water": target_high_water,
            "sequence_last_value": last_value,
            "sequence_is_called": is_called,
        }

    @staticmethod
    def _foreign_key_checks(
        connection: Any, table_names: set[str]
    ) -> list[dict[str, Any]]:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    """
                    SELECT con.conname, child.relname AS child_table,
                           child_col.attname AS child_column,
                           parent.relname AS parent_table,
                           parent_col.attname AS parent_column
                    FROM pg_constraint con
                    JOIN pg_class child ON child.oid = con.conrelid
                    JOIN pg_namespace ns ON ns.oid = child.relnamespace
                    JOIN pg_class parent ON parent.oid = con.confrelid
                    JOIN pg_attribute child_col ON child_col.attrelid = child.oid
                         AND child_col.attnum = con.conkey[1]
                    JOIN pg_attribute parent_col ON parent_col.attrelid = parent.oid
                         AND parent_col.attnum = con.confkey[1]
                    WHERE con.contype = 'f' AND ns.nspname = current_schema()
                    ORDER BY child.relname, con.conname
                    """
                )
                constraints = cursor.fetchall()
                results = []
                for row in constraints:
                    child = str(_row_value(row, "child_table", 1))
                    if child not in table_names:
                        continue
                    child_column = str(_row_value(row, "child_column", 2))
                    parent = str(_row_value(row, "parent_table", 3))
                    parent_column = str(_row_value(row, "parent_column", 4))
                    cursor.execute(
                        f"SELECT COUNT(*) AS count FROM {child} c LEFT JOIN {parent} p "
                        f"ON p.{parent_column} = c.{child_column} "
                        f"WHERE c.{child_column} IS NOT NULL AND p.{parent_column} IS NULL"
                    )
                    count = cursor.fetchone()
                    results.append(
                        {
                            "constraint": str(_row_value(row, "conname", 0)),
                            "child_table": child,
                            "parent_table": parent,
                            "orphan_count": int(_row_value(count, "count", 0) or 0),
                        }
                    )
        return results
