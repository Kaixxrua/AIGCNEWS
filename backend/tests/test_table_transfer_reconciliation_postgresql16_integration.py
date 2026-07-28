from __future__ import annotations

import os
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from backend.app.core.postgres_database import PostgresDatabaseLifecycle, create_postgres_pool
from backend.app.core.postgres_migrations import PostgresMigrationRunner
from backend.app.services.application_data_transfer import APPLICATION_TABLE_TRANSFER_BY_NAME
from backend.app.services.table_transfer_reconciliation import (
    TableTransferReconciliationService,
    TransferReconciliationError,
)

pytestmark = pytest.mark.skipif(
    os.getenv("POSTGRES_INTEGRATION") != "1",
    reason="set POSTGRES_INTEGRATION=1 to run PostgreSQL 16 integration tests",
)


class EmptyMysql:
    @contextmanager
    def transaction(self):
        cursor = SimpleNamespace()
        cursor.execute = lambda *args, **kwargs: None
        cursor.fetchall = lambda: []
        connection = SimpleNamespace(cursor=lambda: _CursorContext(cursor))
        yield connection


class _CursorContext:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *args):
        return None


@pytest.fixture
def database():
    lifecycle = PostgresDatabaseLifecycle(create_postgres_pool)
    lifecycle.open()
    PostgresMigrationRunner(lifecycle).apply()
    with lifecycle.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE users RESTART IDENTITY CASCADE")
            cursor.execute("DELETE FROM project_catalog_migration_runs WHERE job_id = %s", ("reconcile-pg16",))
            cursor.execute(
                """
                INSERT INTO project_catalog_migration_runs
                    (job_id, source_identity_sha256, target_database, target_schema,
                     schema_version, mode, options_json, status, completed_at)
                VALUES (%s, %s, current_database(), current_schema(), 6,
                        'load', '{}'::jsonb, 'completed', CURRENT_TIMESTAMP)
                """,
                ("reconcile-pg16", "0" * 64),
            )
    try:
        yield lifecycle
    finally:
        lifecycle.close()


def test_postgresql16_reconciliation_checks_terminal_gate_fk_and_empty_sequences(database) -> None:
    spec = APPLICATION_TABLE_TRANSFER_BY_NAME["users"]
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO project_catalog_migration_checkpoints (job_id, table_name, status) VALUES (%s, %s, 'completed')",
                ("reconcile-pg16", "users"),
            )
    service = TableTransferReconciliationService(
        mysql=EmptyMysql(),
        postgres=database,
        table_specs=(spec,),
        minimum_schema_version=6,
    )
    result = service.verify(
        job_id="reconcile-pg16",
        target_database=os.getenv("POSTGRES_DB", "aigcnews_test"),
        target_schema="public",
        batch_size=2,
    )
    assert result["status"] == "match"
    assert result["tables"][0]["identity"] == {
        "status": "match",
        "source_high_water": None,
        "target_high_water": None,
        "sequence_last_value": 1,
        "sequence_is_called": False,
    }
    assert all(check["orphan_count"] == 0 for check in result["foreign_keys"])

    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE project_catalog_migration_checkpoints SET status = 'running' WHERE job_id = %s",
                ("reconcile-pg16",),
            )
    with pytest.raises(TransferReconciliationError, match="not all completed"):
        service.verify(
            job_id="reconcile-pg16",
            target_database=os.getenv("POSTGRES_DB", "aigcnews_test"),
            target_schema="public",
        )
