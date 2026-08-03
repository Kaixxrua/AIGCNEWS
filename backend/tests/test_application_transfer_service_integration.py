from __future__ import annotations

import os
from datetime import datetime
from types import SimpleNamespace

import pytest

from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    create_postgres_pool,
)
from backend.app.core.postgres_migrations import PostgresMigrationRunner
from backend.app.services.application_data_transfer import (
    APPLICATION_TABLE_TRANSFER_BY_NAME,
    APPLICATION_TABLE_TRANSFER_SPECS,
)
from backend.app.services.application_transfer_service import ApplicationTransferService
from backend.app.services.project_catalog_transfer import TableCheckpoint

pytestmark = pytest.mark.skipif(
    os.getenv("POSTGRES_INTEGRATION") != "1",
    reason="set POSTGRES_INTEGRATION=1 to run PostgreSQL integration tests",
)


@pytest.fixture
def database():
    lifecycle = PostgresDatabaseLifecycle(create_postgres_pool)
    lifecycle.open()
    PostgresMigrationRunner(lifecycle).apply()
    with lifecycle.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE users RESTART IDENTITY CASCADE")
            cursor.execute(
                "DELETE FROM project_catalog_migration_runs WHERE job_id = %s",
                ("application-transfer-integration",),
            )
            cursor.execute(
                """
                INSERT INTO project_catalog_migration_runs
                    (job_id, source_identity_sha256, target_database,
                     target_schema, schema_version, mode, options_json, status)
                VALUES (%s, %s, current_database(), current_schema(), 6,
                        'load', '{}'::jsonb, 'running')
                """,
                ("application-transfer-integration", "0" * 64),
            )
            for spec in APPLICATION_TABLE_TRANSFER_SPECS:
                cursor.execute(
                    """
                    INSERT INTO project_catalog_migration_checkpoints
                        (job_id, table_name, status)
                    VALUES (%s, %s, 'pending')
                    """,
                    ("application-transfer-integration", spec.name),
                )
    try:
        yield lifecycle
    finally:
        lifecycle.close()


def test_application_batch_writes_jsonb_and_repairs_identity(database) -> None:
    transfer = ApplicationTransferService(
        mysql=object(),
        postgres=database,
        config=SimpleNamespace(app_env="test"),
    )  # type: ignore[arg-type]
    users = APPLICATION_TABLE_TRANSFER_BY_NAME["users"]
    messages = APPLICATION_TABLE_TRANSFER_BY_NAME["chat_messages"]

    with database.connection() as connection:
        transfer._write_table_batch(
            connection,
            spec=users,
            job_id="application-transfer-integration",
            checkpoint=TableCheckpoint({}, 0, 0, "pending"),
            rows=[
                {
                    "id": 41,
                    "phone": None,
                    "email": "transfer@example.com",
                    "email_verified": True,
                    "invite_code_used": None,
                    "username": None,
                    "hashed_password": "hash",
                    "role": "user",
                    "created_at": datetime(2026, 1, 1),
                }
            ],
        )
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversations (id, user_id, title)
                    VALUES (51, 41, 'transfer')
                    """
                )
        transfer._write_table_batch(
            connection,
            spec=messages,
            job_id="application-transfer-integration",
            checkpoint=TableCheckpoint({}, 0, 0, "pending"),
            rows=[
                {
                    "id": 61,
                    "conversation_id": 51,
                    "role": "assistant",
                    "content": "answer",
                    "thinking": None,
                    "sources_json": '[{"id":"doc-1"}]',
                    "attachments_json": "[]",
                    "status": "done",
                    "parent_message_id": None,
                    "created_at": datetime(2026, 1, 2),
                    "updated_at": datetime(2026, 1, 2),
                }
            ],
        )
        repairs = transfer._repair_identity_sequences(
            connection, APPLICATION_TABLE_TRANSFER_SPECS
        )
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT sources_json, attachments_json FROM chat_messages WHERE id = 61"
                )
                row = cursor.fetchone()
                cursor.execute(
                    "INSERT INTO users (email, hashed_password) VALUES (%s, %s) RETURNING id",
                    ("next@example.com", "hash"),
                )
                next_user = cursor.fetchone()

    assert row["sources_json"] == [{"id": "doc-1"}]
    assert row["attachments_json"] == []
    assert next_user["id"] == 42
    assert {repair["table"] for repair in repairs} == {
        spec.name for spec in APPLICATION_TABLE_TRANSFER_SPECS if spec.identity_column
    }
