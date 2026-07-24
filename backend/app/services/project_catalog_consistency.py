from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from backend.app.core.database import DatabaseLifecycle, mysql_database
from backend.app.core.postgres_database import PostgresDatabaseLifecycle, postgres_database
from backend.app.services.project_catalog_sequence import ProjectCatalogSequenceService
from backend.app.services.project_catalog_transfer import (
    DEFAULT_BATCH_SIZE,
    TABLE_TRANSFER_SPECS,
    ProjectCatalogTransferService,
    TableTransferSpec,
    TargetIdentity,
)


@dataclass(frozen=True)
class TableDigest:
    count: int
    primary_key_sha256: str
    full_row_sha256: str
    minimum_key: dict[str, Any] | None
    maximum_key: dict[str, Any] | None


def _length_prefixed(payload: bytes) -> bytes:
    return len(payload).to_bytes(8, "big") + payload


def _canonical_value(value: Any) -> list[Any]:
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["boolean", value]
    if isinstance(value, int):
        return ["integer", str(value)]
    if isinstance(value, float):
        if math.isnan(value):
            encoded = "nan"
        elif math.isinf(value):
            encoded = "infinity" if value > 0 else "-infinity"
        else:
            encoded = value.hex()
        return ["float64", encoded]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("canonical datetime must be timezone-aware")
        utc_value = value.astimezone(timezone.utc)
        return ["datetime_utc", utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    return ["text", str(value)]


def canonical_row_bytes(spec: TableTransferSpec, row: Mapping[str, Any]) -> bytes:
    values = [[column, *_canonical_value(row.get(column))] for column in spec.columns]
    return json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def canonical_key_bytes(spec: TableTransferSpec, row: Mapping[str, Any]) -> bytes:
    values = [[column, *_canonical_value(row.get(column))] for column in spec.cursor_columns]
    return json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def digest_rows(spec: TableTransferSpec, rows: Iterable[Mapping[str, Any]]) -> TableDigest:
    key_digest = hashlib.sha256()
    row_digest = hashlib.sha256()
    count = 0
    minimum_key: dict[str, Any] | None = None
    maximum_key: dict[str, Any] | None = None
    for row in rows:
        key = {column: row.get(column) for column in spec.cursor_columns}
        if minimum_key is None:
            minimum_key = key
        maximum_key = key
        key_digest.update(_length_prefixed(canonical_key_bytes(spec, row)))
        row_digest.update(_length_prefixed(canonical_row_bytes(spec, row)))
        count += 1
    return TableDigest(
        count=count,
        primary_key_sha256=key_digest.hexdigest(),
        full_row_sha256=row_digest.hexdigest(),
        minimum_key=minimum_key,
        maximum_key=maximum_key,
    )


class ProjectCatalogConsistencyService:
    """Build value-free consistency evidence across MySQL and PostgreSQL."""

    def __init__(
        self,
        *,
        mysql: DatabaseLifecycle = mysql_database,
        postgres: PostgresDatabaseLifecycle = postgres_database,
        config: Any | None = None,
    ) -> None:
        self._transfer = ProjectCatalogTransferService(
            mysql=mysql,
            postgres=postgres,
            config=config,
        )
        self._mysql = mysql
        self._postgres = postgres

    def verify(
        self,
        *,
        target_database: str,
        target_schema: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        source_timezone: str = "UTC",
        stability_passes: int = 2,
    ) -> dict[str, Any]:
        batch_size = self._transfer._validate_batch_size(batch_size)
        source_timezone = self._transfer._validate_source_timezone(source_timezone)
        passes = int(stability_passes)
        if passes < 1 or passes > 3:
            raise ValueError("stability passes must be between 1 and 3")
        target = self._transfer._inspect_target(target_database, target_schema)
        source_reports = [
            self._digest_source_catalog(batch_size, source_timezone)
            for _ in range(passes)
        ]
        target_report = self._digest_target_catalog(batch_size, source_timezone)
        source_stable = all(report == source_reports[0] for report in source_reports[1:])
        table_reports = []
        all_match = True
        for spec in TABLE_TRANSFER_SPECS:
            source_digest = source_reports[-1][spec.name]
            target_digest = target_report[spec.name]
            matches = source_digest == target_digest
            all_match = all_match and matches
            table_reports.append(
                {
                    "table": spec.name,
                    "status": "match" if matches else "mismatch",
                    "source": self._digest_dict(source_digest),
                    "target": self._digest_dict(target_digest),
                }
            )
        references = self._reference_checks()
        all_match = all_match and all(value == 0 for value in references.values())
        verified = all_match and source_stable
        sequences = self._sequence_checks(target)
        ready = verified and sequences["status"] == "ready"
        return {
            "status": "match" if verified else "mismatch",
            "readiness_status": "ready" if ready else "not_ready",
            "stable": source_stable,
            "source_passes": passes,
            "tables": table_reports,
            "references": references,
            "identity_sequences": sequences["tables"],
            "target_database": target.database,
            "target_schema": target.schema,
            "schema_version": target.schema_version,
        }

    def _sequence_checks(self, target: TargetIdentity) -> dict[str, Any]:
        return ProjectCatalogSequenceService(
            mysql=self._mysql,
            postgres=self._postgres,
        ).inspect(
            target_database=target.database,
            target_schema=target.schema,
        )

    def _digest_source_catalog(
        self, batch_size: int, source_timezone: str
    ) -> dict[str, TableDigest]:
        return {
            spec.name: digest_rows(
                spec,
                self._iter_source_rows(spec, batch_size, source_timezone),
            )
            for spec in TABLE_TRANSFER_SPECS
        }

    def _digest_target_catalog(
        self, batch_size: int, source_timezone: str
    ) -> dict[str, TableDigest]:
        return {
            spec.name: digest_rows(
                spec,
                self._iter_target_rows(spec, batch_size, source_timezone),
            )
            for spec in TABLE_TRANSFER_SPECS
        }

    def _iter_source_rows(
        self,
        spec: TableTransferSpec,
        batch_size: int,
        source_timezone: str,
    ) -> Iterable[dict[str, Any]]:
        after: dict[str, Any] = {}
        while True:
            rows = self._transfer._read_table_batch(
                spec,
                after=after,
                batch_size=batch_size,
                source_timezone=source_timezone,
            )
            if not rows:
                return
            yield from rows
            after = self._transfer._cursor_from_row(spec, rows[-1])

    def _iter_target_rows(
        self,
        spec: TableTransferSpec,
        batch_size: int,
        source_timezone: str,
    ) -> Iterable[dict[str, Any]]:
        after: dict[str, Any] = {}
        columns = ", ".join(spec.columns)
        cursor_sql = ", ".join(
            f'{column} COLLATE "C"' if column in spec.text_cursor_columns else column
            for column in spec.cursor_columns
        )
        while True:
            if after:
                placeholders = ", ".join(["%s"] * len(spec.cursor_columns))
                where = f"WHERE ({cursor_sql}) > ({placeholders})"
                params = tuple(after[column] for column in spec.cursor_columns) + (batch_size,)
            else:
                where = ""
                params = (batch_size,)
            with self._postgres.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"SELECT {columns} FROM {spec.name} {where} "
                        f"ORDER BY {cursor_sql} ASC LIMIT %s",
                        params,
                    )
                    rows = [dict(row) for row in cursor.fetchall()]
            rows = [
                self._transfer._encode_source_row(
                    spec, row, source_timezone=source_timezone
                )
                for row in rows
            ]
            if not rows:
                return
            yield from rows
            after = self._transfer._cursor_from_row(spec, rows[-1])

    def _reference_checks(self) -> dict[str, int]:
        statements = {
            "alias_orphans": """
                SELECT COUNT(*) AS count
                FROM github_repo_aliases a
                LEFT JOIN github_repo_candidates c
                  ON c.repo_id = a.canonical_repo_id
                WHERE c.repo_id IS NULL
            """,
            "website_enrichment_orphans": """
                SELECT COUNT(*) AS count
                FROM tool_website_enrichments e
                LEFT JOIN tool_websites w ON w.id = e.website_id
                WHERE w.id IS NULL
            """,
            "user_website_orphans": """
                SELECT COUNT(*) AS count
                FROM user_tool_websites u
                LEFT JOIN tool_websites w ON w.id = u.website_id
                WHERE w.id IS NULL
            """,
            "user_override_orphans": """
                SELECT COUNT(*) AS count
                FROM user_tool_website_overrides o
                LEFT JOIN tool_websites w ON w.id = o.website_id
                WHERE w.id IS NULL
            """,
            "website_favorite_orphans": """
                SELECT COUNT(*) AS count
                FROM project_favorites f
                LEFT JOIN tool_websites w
                  ON f.project_source = 'website'
                 AND f.project_id = CAST(w.id AS TEXT)
                WHERE f.project_source = 'website' AND w.id IS NULL
            """,
            "github_favorite_orphans": """
                SELECT COUNT(*) AS count
                FROM project_favorites f
                LEFT JOIN github_repo_candidates c
                  ON f.project_source = 'github'
                 AND f.project_id = c.repo_id
                WHERE f.project_source = 'github' AND c.repo_id IS NULL
            """,
            "candidate_name_collisions": """
                SELECT COUNT(*) AS count
                FROM (
                    SELECT LOWER(full_name)
                    FROM github_repo_candidates
                    GROUP BY LOWER(full_name)
                    HAVING COUNT(*) > 1
                ) collisions
            """,
        }
        checks: dict[str, int] = {}
        with self._postgres.transaction() as connection:
            with connection.cursor() as cursor:
                for name, statement in statements.items():
                    cursor.execute(statement)
                    row = cursor.fetchone()
                    checks[name] = int(
                        row.get("count", 0) if isinstance(row, dict) else row[0]
                    )
        return checks

    @staticmethod
    def _digest_dict(value: TableDigest) -> dict[str, Any]:
        return {
            "count": value.count,
            "primary_key_sha256": value.primary_key_sha256,
            "full_row_sha256": value.full_row_sha256,
            "minimum_key": value.minimum_key,
            "maximum_key": value.maximum_key,
        }
