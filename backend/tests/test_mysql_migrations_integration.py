from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.core.database import DatabaseLifecycle, create_mysql_pool
from backend.app.core.mysql_migrations import MySQLMigrationRunner


def _settings() -> SimpleNamespace:
    database = os.getenv("TEST_MYSQL_DATABASE", "").strip()
    if not database:
        pytest.skip("TEST_MYSQL_DATABASE is not configured")
    if "test" not in database.casefold():
        pytest.skip("TEST_MYSQL_DATABASE must contain 'test'")
    return SimpleNamespace(
        mysql_host=os.getenv("TEST_MYSQL_HOST", "127.0.0.1"),
        mysql_port=int(os.getenv("TEST_MYSQL_PORT", "3306")),
        mysql_user=os.getenv("TEST_MYSQL_USER", ""),
        mysql_password=os.getenv("TEST_MYSQL_PASSWORD", ""),
        mysql_database=database,
    )


def test_live_mysql_outbox_migration_is_repeatable_and_introspectable() -> None:
    config = _settings()
    database = DatabaseLifecycle(lambda: create_mysql_pool(config=config))
    try:
        runner = MySQLMigrationRunner(database)
        applied = runner.apply()
        assert [migration.version for migration in applied] in ([1], [])
        assert runner.apply() == []
        assert all(status.applied for status in runner.status())
        with database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = 'project_catalog_outbox'
                    """,
                    (config.mysql_database,),
                )
                columns = {
                    str(row.get("column_name") or row.get("COLUMN_NAME"))
                    for row in cursor.fetchall()
                }
                cursor.execute(
                    """
                    SELECT DISTINCT index_name
                    FROM information_schema.statistics
                    WHERE table_schema = %s AND table_name = 'project_catalog_outbox'
                    """,
                    (config.mysql_database,),
                )
                indexes = {
                    str(row.get("index_name") or row.get("INDEX_NAME"))
                    for row in cursor.fetchall()
                }
                cursor.execute(
                    "SELECT version, filename FROM app_mysql_schema_migrations"
                )
                ledger: list[dict[str, Any]] = cursor.fetchall()
        assert {
            "event_id",
            "aggregate_type",
            "aggregate_key",
            "status",
            "lease_token",
            "lease_expires_at",
        } <= columns
        assert {
            "uq_project_catalog_outbox_event_id",
            "idx_project_catalog_outbox_claim",
            "idx_project_catalog_outbox_aggregate",
            "idx_project_catalog_outbox_lease",
        } <= indexes
        assert ledger == [
            {"version": 1, "filename": "0001_project_catalog_outbox.sql"}
        ]
    finally:
        database.close()
