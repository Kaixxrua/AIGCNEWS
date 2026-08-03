from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from psycopg import sql

from backend.app.core.database import DatabaseLifecycle, mysql_database
from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)
from backend.app.services.project_catalog_transfer import (
    TABLE_TRANSFER_SPECS,
    ProjectCatalogTransferSafetyError,
    ProjectCatalogTransferService,
    TableTransferSpec,
)


@dataclass(frozen=True)
class IdentitySequenceStatus:
    table: str
    column: str
    sequence: str | None
    maximum_id: int | None
    last_value: int | None
    is_called: bool | None
    next_value: int | None
    status: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProjectCatalogSequenceService:
    """Inspect and explicitly repair imported PostgreSQL identity sequences."""

    def __init__(
        self,
        *,
        mysql: DatabaseLifecycle = mysql_database,
        postgres: PostgresDatabaseLifecycle = postgres_database,
        config: Any | None = None,
    ) -> None:
        self._postgres = postgres
        self._transfer = ProjectCatalogTransferService(
            mysql=mysql,
            postgres=postgres,
            config=config,
        )

    def inspect(
        self,
        *,
        target_database: str,
        target_schema: str,
    ) -> dict[str, Any]:
        target = self._transfer._inspect_target(target_database, target_schema)
        tables = [
            self._inspect_spec(spec, target_schema=target.schema).as_dict()
            for spec in TABLE_TRANSFER_SPECS
            if spec.identity_column
        ]
        ready = all(item["status"] == "healthy" for item in tables)
        return {
            "status": "ready" if ready else "not_ready",
            "target_database": target.database,
            "target_schema": target.schema,
            "schema_version": target.schema_version,
            "tables": tables,
        }

    def repair(
        self,
        *,
        target_database: str,
        target_schema: str,
        apply: bool = False,
        production_authorized: bool = False,
    ) -> dict[str, Any]:
        target = self._transfer._inspect_target(target_database, target_schema)
        if apply:
            self._transfer._validate_production_authorization(production_authorized)
        tables = []
        for spec in TABLE_TRANSFER_SPECS:
            if not spec.identity_column:
                continue
            before = self._inspect_spec(spec, target_schema=target.schema)
            action = "unchanged" if before.status == "healthy" else "planned"
            after = before
            if apply and before.status == "behind":
                after = self._repair_spec(spec, target_schema=target.schema)
                action = "repaired" if after.status == "healthy" else "failed"
            elif apply and before.status == "missing":
                action = "failed"
            tables.append(
                {
                    "table": spec.name,
                    "column": spec.identity_column,
                    "action": action,
                    "before": before.as_dict(),
                    "after": after.as_dict(),
                }
            )
        ready = all(item["after"]["status"] == "healthy" for item in tables)
        return {
            "status": "ready" if ready else "not_ready",
            "applied": bool(apply),
            "target_database": target.database,
            "target_schema": target.schema,
            "schema_version": target.schema_version,
            "tables": tables,
        }

    def _inspect_spec(
        self,
        spec: TableTransferSpec,
        *,
        target_schema: str,
        connection: Any | None = None,
    ) -> IdentitySequenceStatus:
        column = spec.identity_column
        if not column:
            raise ProjectCatalogTransferSafetyError("table has no imported identity column")

        def inspect(active_connection: Any) -> IdentitySequenceStatus:
            with active_connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("SELECT MAX({}) AS maximum_id FROM {}.{}").format(
                        sql.Identifier(column),
                        sql.Identifier(target_schema),
                        sql.Identifier(spec.name),
                    )
                )
                maximum_row = cursor.fetchone()
                maximum = self._row_value(maximum_row, "maximum_id")
                cursor.execute(
                    "SELECT pg_get_serial_sequence(%s, %s) AS sequence_name",
                    (f"{target_schema}.{spec.name}", column),
                )
                sequence_row = cursor.fetchone()
                sequence_name = self._row_value(sequence_row, "sequence_name")
                if not sequence_name:
                    return IdentitySequenceStatus(
                        spec.name,
                        column,
                        None,
                        int(maximum) if maximum is not None else None,
                        None,
                        None,
                        None,
                        "missing",
                    )
                cursor.execute(
                    sql.SQL("SELECT last_value, is_called FROM {}").format(
                        self._qualified_identifier(str(sequence_name))
                    )
                )
                state = cursor.fetchone()
                last_value = int(self._row_value(state, "last_value"))
                is_called = bool(self._row_value(state, "is_called", 1))
            maximum_id = int(maximum) if maximum is not None else None
            next_value = last_value + 1 if is_called else last_value
            healthy = maximum_id is None or next_value > maximum_id
            return IdentitySequenceStatus(
                spec.name,
                column,
                str(sequence_name),
                maximum_id,
                last_value,
                is_called,
                next_value,
                "healthy" if healthy else "behind",
            )

        if connection is not None:
            return inspect(connection)
        with self._postgres.transaction() as active_connection:
            return inspect(active_connection)

    def _repair_spec(
        self,
        spec: TableTransferSpec,
        *,
        target_schema: str,
    ) -> IdentitySequenceStatus:
        with self._postgres.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("LOCK TABLE {}.{} IN ACCESS EXCLUSIVE MODE").format(
                        sql.Identifier(target_schema),
                        sql.Identifier(spec.name),
                    )
                )
            current = self._inspect_spec(
                spec,
                target_schema=target_schema,
                connection=connection,
            )
            if current.status != "behind" or current.maximum_id is None:
                return current
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT setval(%s::regclass, %s, true)",
                    (current.sequence, current.maximum_id),
                )
            return self._inspect_spec(
                spec,
                target_schema=target_schema,
                connection=connection,
            )

    @staticmethod
    def _qualified_identifier(value: str) -> Any:
        parts = value.split(".", 1)
        return sql.Identifier(*parts)

    @staticmethod
    def _row_value(row: Any, key: str, index: int = 0) -> Any:
        if isinstance(row, dict):
            return row.get(key)
        return row[index] if row is not None else None
