from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.app.core.database import DatabaseLifecycle, mysql_database


APPLICATION_TABLES = frozenset(
    {
        "briefing_subscriptions",
        "briefings",
        "chat_attachments",
        "chat_messages",
        "conversations",
        "document_rank_snapshots",
        "documents",
        "github_project_semantic_sources",
        "github_repo_aliases",
        "github_repo_candidates",
        "github_repo_daily_metrics",
        "github_repo_enrichments",
        "github_repo_recommendations",
        "github_repo_snapshots",
        "github_trending_hits",
        "ingestion_tasks",
        "mcp_server_configs",
        "project_favorites",
        "rag_evaluations",
        "runtime_provider_settings",
        "tool_website_enrichments",
        "tool_websites",
        "user_mcp_tokens",
        "user_tool_website_overrides",
        "user_tool_websites",
        "users",
    }
)
CATALOG_TABLES = frozenset(
    {
        "github_project_semantic_sources",
        "github_repo_aliases",
        "github_repo_candidates",
        "github_repo_daily_metrics",
        "github_repo_enrichments",
        "github_repo_recommendations",
        "github_repo_snapshots",
        "github_trending_hits",
        "project_favorites",
        "tool_website_enrichments",
        "tool_websites",
        "user_tool_website_overrides",
        "user_tool_websites",
    }
)
OPERATIONAL_TABLES = frozenset(
    {"app_mysql_schema_migrations", "project_catalog_outbox"}
)
_SENSITIVE_NAME_RE = re.compile(
    r"(?:api[_-]?key|auth|credential|password|secret|token)", re.IGNORECASE
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_$]+$")
DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "mysql_to_postgres_manifest.json"
)


class MySQLSchemaInventoryService:
    """Collect read-only, secret-safe evidence about the live MySQL schema."""

    def __init__(
        self,
        database: DatabaseLifecycle = mysql_database,
        *,
        manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
    ) -> None:
        self._database = database
        self._manifest_path = Path(manifest_path)

    def collect(self, *, exact_counts: bool = True) -> dict[str, Any]:
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
                database_name, server_version, session_timezone = self._identity(cursor)
                tables = self._tables(cursor, database_name)
                columns = self._grouped(
                    self._columns(cursor, database_name), key="table_name"
                )
                indexes = self._grouped(
                    self._indexes(cursor, database_name), key="table_name"
                )
                foreign_keys = self._grouped(
                    self._foreign_keys(cursor, database_name), key="table_name"
                )
                table_records = []
                for table in tables:
                    name = str(table["table_name"])
                    create_sha256 = self._create_statement_sha256(cursor, name)
                    exact_count = self._exact_count(cursor, name) if exact_counts else None
                    table_records.append(
                        {
                            **table,
                            "classification": self._classification(name),
                            "exact_row_count": exact_count,
                            "create_statement_sha256": create_sha256,
                            "columns": columns.get(name, []),
                            "indexes": indexes.get(name, []),
                            "foreign_keys": foreign_keys.get(name, []),
                        }
                    )

        manifest = self._load_manifest()
        manifest_tables = set(manifest["tables"])
        live_tables = {str(table["table_name"]) for table in table_records}
        unknown_tables = sorted(live_tables.difference(manifest_tables))
        missing_manifest_tables = sorted(manifest_tables.difference(live_tables))
        missing_application_tables = sorted(APPLICATION_TABLES.difference(live_tables))
        for table in table_records:
            manifest_entry = manifest["tables"].get(str(table["table_name"]))
            if manifest_entry is not None:
                table["classification"] = manifest_entry["classification"]
                table["disposition"] = manifest_entry["disposition"]
                if "target" in manifest_entry:
                    table["target"] = manifest_entry["target"]
                if "reason" in manifest_entry:
                    table["reason"] = manifest_entry["reason"]
        artifact: dict[str, Any] = {
            "artifact_version": 1,
            "kind": "mysql_schema_inventory",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "source": {
                "database": database_name,
                "server_version": server_version,
                "session_timezone": session_timezone,
            },
            "summary": {
                "table_count": len(table_records),
                "unknown_tables": unknown_tables,
                "missing_manifest_tables": missing_manifest_tables,
                "missing_application_tables": missing_application_tables,
                "ready_for_schema_design": not unknown_tables
                and not missing_manifest_tables
                and not missing_application_tables,
            },
            "tables": table_records,
        }
        artifact["artifact_sha256"] = self._digest(artifact)
        return artifact

    def _load_manifest(self) -> dict[str, Any]:
        manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        if manifest.get("manifest_version") != 1:
            raise ValueError("unsupported MySQL-to-PostgreSQL manifest version")
        tables = manifest.get("tables")
        if not isinstance(tables, dict) or not tables:
            raise ValueError("MySQL-to-PostgreSQL manifest tables are required")
        allowed_dispositions = {
            "migrate",
            "already_migrated",
            "archive_only",
            "retire_after_cutover",
        }
        for table_name, entry in tables.items():
            self._quoted_identifier(str(table_name))
            if not isinstance(entry, dict):
                raise ValueError("MySQL-to-PostgreSQL manifest entry must be an object")
            if entry.get("disposition") not in allowed_dispositions:
                raise ValueError("invalid MySQL-to-PostgreSQL table disposition")
        return manifest

    @staticmethod
    def _identity(cursor: Any) -> tuple[str, str, str]:
        cursor.execute(
            "SELECT DATABASE() AS database_name, @@version AS server_version, "
            "@@session.time_zone AS session_timezone"
        )
        row = cursor.fetchone() or {}
        return (
            str(row.get("database_name") or ""),
            str(row.get("server_version") or ""),
            str(row.get("session_timezone") or ""),
        )

    @staticmethod
    def _tables(cursor: Any, database_name: str) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT
                TABLE_NAME AS table_name,
                ENGINE AS engine,
                TABLE_COLLATION AS collation,
                TABLE_ROWS AS estimated_row_count,
                DATA_LENGTH AS data_bytes,
                INDEX_LENGTH AS index_bytes,
                AUTO_INCREMENT AS auto_increment
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
            """,
            (database_name,),
        )
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _columns(cursor: Any, database_name: str) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT
                TABLE_NAME AS table_name,
                ORDINAL_POSITION AS ordinal_position,
                COLUMN_NAME AS column_name,
                COLUMN_TYPE AS column_type,
                IS_NULLABLE AS is_nullable,
                COLUMN_DEFAULT AS column_default,
                EXTRA AS extra,
                COLLATION_NAME AS collation
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME, ORDINAL_POSITION
            """,
            (database_name,),
        )
        rows = []
        for raw_row in cursor.fetchall():
            row = dict(raw_row)
            if _SENSITIVE_NAME_RE.search(str(row.get("column_name") or "")):
                row["column_default"] = (
                    "<redacted>" if row.get("column_default") is not None else None
                )
            rows.append(row)
        return rows

    @staticmethod
    def _indexes(cursor: Any, database_name: str) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT
                TABLE_NAME AS table_name,
                INDEX_NAME AS index_name,
                NON_UNIQUE AS non_unique,
                SEQ_IN_INDEX AS sequence_in_index,
                COLUMN_NAME AS column_name,
                COLLATION AS collation,
                SUB_PART AS prefix_length,
                INDEX_TYPE AS index_type
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
            """,
            (database_name,),
        )
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _foreign_keys(cursor: Any, database_name: str) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT
                kcu.TABLE_NAME AS table_name,
                kcu.CONSTRAINT_NAME AS constraint_name,
                kcu.COLUMN_NAME AS column_name,
                kcu.REFERENCED_TABLE_NAME AS referenced_table_name,
                kcu.REFERENCED_COLUMN_NAME AS referenced_column_name,
                rc.UPDATE_RULE AS update_rule,
                rc.DELETE_RULE AS delete_rule
            FROM information_schema.KEY_COLUMN_USAGE AS kcu
            JOIN information_schema.REFERENTIAL_CONSTRAINTS AS rc
              ON rc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA
             AND rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
             AND rc.TABLE_NAME = kcu.TABLE_NAME
            WHERE kcu.CONSTRAINT_SCHEMA = %s
              AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
            ORDER BY kcu.TABLE_NAME, kcu.CONSTRAINT_NAME, kcu.ORDINAL_POSITION
            """,
            (database_name,),
        )
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _grouped(
        rows: list[dict[str, Any]], *, key: str
    ) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            group_name = str(row.pop(key))
            grouped.setdefault(group_name, []).append(row)
        return grouped

    @staticmethod
    def _classification(table_name: str) -> str:
        if table_name in OPERATIONAL_TABLES:
            return "operational"
        if table_name in CATALOG_TABLES:
            return "catalog"
        if table_name in APPLICATION_TABLES:
            return "application"
        return "unknown"

    @staticmethod
    def _quoted_identifier(identifier: str) -> str:
        if not _IDENTIFIER_RE.fullmatch(identifier):
            raise ValueError("unsafe MySQL identifier in schema inventory")
        return f"`{identifier}`"

    def _exact_count(self, cursor: Any, table_name: str) -> int:
        cursor.execute(
            f"SELECT COUNT(*) AS row_count FROM {self._quoted_identifier(table_name)}"
        )
        row = cursor.fetchone() or {}
        return int(row.get("row_count") or 0)

    def _create_statement_sha256(self, cursor: Any, table_name: str) -> str:
        cursor.execute(f"SHOW CREATE TABLE {self._quoted_identifier(table_name)}")
        row: Mapping[str, Any] = cursor.fetchone() or {}
        statement = row.get("Create Table") or row.get("Create View") or ""
        return hashlib.sha256(str(statement).encode("utf-8")).hexdigest()

    @staticmethod
    def _digest(artifact: Mapping[str, Any]) -> str:
        payload = dict(artifact)
        payload.pop("artifact_sha256", None)
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
