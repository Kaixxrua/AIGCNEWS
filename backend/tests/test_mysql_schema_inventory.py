from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager

from backend.app.services.mysql_schema_inventory import MySQLSchemaInventoryService


def write_manifest(tmp_path, *table_names: str):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "tables": {
                    name: {
                        "classification": "application" if name == "users" else "archive",
                        "disposition": "migrate" if name == "users" else "archive_only",
                    }
                    for name in table_names
                },
            }
        ),
        encoding="utf-8",
    )
    return path


class FakeCursor:
    def __init__(self) -> None:
        self._rows: list[dict[str, object]] = []
        self.executed: list[tuple[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql: str, params=None) -> None:
        normalized = " ".join(sql.split())
        self.executed.append((normalized, params))
        if normalized.startswith("SELECT DATABASE()"):
            self._rows = [{"database_name": "rag_aigc", "server_version": "8.0.36", "session_timezone": "+00:00"}]
        elif "FROM information_schema.TABLES" in normalized:
            self._rows = [
                {
                    "table_name": "users",
                    "engine": "InnoDB",
                    "collation": "utf8mb4_unicode_ci",
                    "estimated_row_count": 2,
                    "data_bytes": 1024,
                    "index_bytes": 256,
                    "auto_increment": 3,
                },
                {
                    "table_name": "unexpected_table",
                    "engine": "InnoDB",
                    "collation": "utf8mb4_unicode_ci",
                    "estimated_row_count": 0,
                    "data_bytes": 0,
                    "index_bytes": 0,
                    "auto_increment": None,
                },
            ]
        elif "FROM information_schema.COLUMNS" in normalized:
            self._rows = [
                {
                    "table_name": "users",
                    "ordinal_position": 1,
                    "column_name": "id",
                    "column_type": "int",
                    "is_nullable": "NO",
                    "column_default": None,
                    "extra": "auto_increment",
                    "collation": None,
                },
                {
                    "table_name": "users",
                    "ordinal_position": 2,
                    "column_name": "password_hash",
                    "column_type": "varchar(255)",
                    "is_nullable": "NO",
                    "column_default": "must-not-leak",
                    "extra": "",
                    "collation": "utf8mb4_unicode_ci",
                },
            ]
        elif "FROM information_schema.STATISTICS" in normalized:
            self._rows = [
                {
                    "table_name": "users",
                    "index_name": "PRIMARY",
                    "non_unique": 0,
                    "sequence_in_index": 1,
                    "column_name": "id",
                    "collation": "A",
                    "prefix_length": None,
                    "index_type": "BTREE",
                }
            ]
        elif "FROM information_schema.KEY_COLUMN_USAGE" in normalized:
            self._rows = []
        elif normalized == "SHOW CREATE TABLE `users`":
            self._rows = [{"Table": "users", "Create Table": "CREATE TABLE users (id INT)"}]
        elif normalized == "SHOW CREATE TABLE `unexpected_table`":
            self._rows = [{"Table": "unexpected_table", "Create Table": "CREATE TABLE unexpected_table (id INT)"}]
        elif normalized == "SELECT COUNT(*) AS row_count FROM `users`":
            self._rows = [{"row_count": 2}]
        elif normalized == "SELECT COUNT(*) AS row_count FROM `unexpected_table`":
            self._rows = [{"row_count": 0}]
        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class FakeDatabase:
    def __init__(self, cursor: FakeCursor) -> None:
        self._connection = FakeConnection(cursor)

    @contextmanager
    def connection(self):
        yield self._connection


def test_inventory_is_read_only_classified_and_secret_safe(tmp_path) -> None:
    cursor = FakeCursor()
    artifact = MySQLSchemaInventoryService(
        FakeDatabase(cursor), manifest_path=write_manifest(tmp_path, "users")
    ).collect()

    assert cursor.executed[0][0] == "SET TRANSACTION READ ONLY"
    assert cursor.executed[1][0] == "START TRANSACTION WITH CONSISTENT SNAPSHOT"
    assert artifact["summary"]["unknown_tables"] == ["unexpected_table"]
    assert artifact["summary"]["missing_manifest_tables"] == []
    assert artifact["summary"]["ready_for_schema_design"] is False
    users = next(table for table in artifact["tables"] if table["table_name"] == "users")
    assert users["classification"] == "application"
    assert users["exact_row_count"] == 2
    assert users["columns"][1]["column_default"] == "<redacted>"
    serialized = json.dumps(artifact, sort_keys=True)
    assert "must-not-leak" not in serialized
    assert "CREATE TABLE users" not in serialized
    assert users["create_statement_sha256"] == hashlib.sha256(
        b"CREATE TABLE users (id INT)"
    ).hexdigest()


def test_inventory_can_skip_expensive_exact_counts(tmp_path) -> None:
    cursor = FakeCursor()
    artifact = MySQLSchemaInventoryService(
        FakeDatabase(cursor),
        manifest_path=write_manifest(tmp_path, "users", "unexpected_table"),
    ).collect(exact_counts=False)

    assert all(table["exact_row_count"] is None for table in artifact["tables"])
    assert not any(sql.startswith("SELECT COUNT(*)") for sql, _ in cursor.executed)


def test_inventory_applies_archive_disposition_from_manifest(tmp_path) -> None:
    cursor = FakeCursor()
    artifact = MySQLSchemaInventoryService(
        FakeDatabase(cursor),
        manifest_path=write_manifest(tmp_path, "users", "unexpected_table"),
    ).collect()

    archived = next(
        table
        for table in artifact["tables"]
        if table["table_name"] == "unexpected_table"
    )
    assert archived["classification"] == "archive"
    assert archived["disposition"] == "archive_only"
    assert artifact["summary"]["unknown_tables"] == []


def test_inventory_digest_is_bound_to_artifact(tmp_path) -> None:
    cursor = FakeCursor()
    artifact = MySQLSchemaInventoryService(
        FakeDatabase(cursor),
        manifest_path=write_manifest(tmp_path, "users", "unexpected_table"),
    ).collect()

    digest = artifact.pop("artifact_sha256")
    assert digest == MySQLSchemaInventoryService._digest(artifact)
