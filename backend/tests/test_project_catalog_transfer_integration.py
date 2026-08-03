from __future__ import annotations

import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

# Keep application settings from discovering a developer .env during this opt-in test.
_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    from backend.app.core.postgres_database import PostgresDatabaseLifecycle
    from backend.app.core.postgres_migrations import PostgresMigrationRunner
    from backend.app.services.project_catalog_transfer import (
        TABLE_TRANSFER_SPECS,
        ProjectCatalogTransferService,
        TableCheckpoint,
    )
finally:
    os.chdir(_IMPORT_CWD)


def _test_dsn() -> str:
    dsn = os.environ.get("TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is required for PostgreSQL integration tests")
    try:
        database = str(conninfo_to_dict(dsn).get("dbname") or "")
    except Exception as exc:
        pytest.skip(f"TEST_POSTGRES_DSN is not a valid PostgreSQL DSN: {exc}")
    if "test" not in database.casefold():
        pytest.skip("TEST_POSTGRES_DSN dbname must contain 'test'")
    return dsn


def _rows() -> dict[str, dict[str, Any]]:
    timestamp = "2026-01-01T00:00:00Z"
    fingerprint = "a" * 64
    return {
        "github_repo_candidates": {
            "repo_id": "owner/repo",
            "full_name": "Owner/Repo",
            "stars": 1,
            "forks": 0,
            "watchers": 0,
            "source_channels": "integration",
            "availability_status": "active",
            "not_found_count": 0,
        },
        "github_repo_aliases": {
            "alias_repo_id": "owner/old-repo",
            "canonical_repo_id": "owner/repo",
            "full_name": "Owner/Old-Repo",
        },
        "github_repo_enrichments": {
            "repo_id": "owner/repo",
            "category_slug": "agents",
            "category_name": "Agents",
            "subcategory_slug": "",
            "subcategory_name": "",
            "description_zh": "测试",
            "confidence": 1.0,
            "source_fingerprint": fingerprint,
            "prompt_version": "v1",
            "model_provider": "test",
            "model_name": "test",
            "status": "succeeded",
        },
        "github_repo_snapshots": {
            "id": 101,
            "repo_id": "owner/repo",
            "snapshot_date": "2026-01-01",
            "captured_at": timestamp,
            "stars": 1,
            "forks": 0,
            "watchers": 0,
            "open_issues": 0,
        },
        "github_repo_daily_metrics": {
            "repo_id": "owner/repo",
            "metric_date": "2026-01-01",
            "stars": 1,
            "forks": 0,
            "watchers": 0,
            "open_issues": 0,
            "previous_stars": 0,
            "daily_star_growth": 1,
            "daily_fork_growth": 0,
            "daily_watcher_growth": 0,
            "daily_growth_available": True,
            "daily_growth_source": "snapshot",
            "scale_corrected_growth_score": 0.0,
            "growth_acceleration_score": 0.0,
            "absolute_growth_score": 0.0,
            "maintenance_activity_score": 0.0,
            "community_engagement_score": 0.0,
            "hot_score": 0.0,
            "score_version": "test",
        },
        "github_trending_hits": {
            "id": 102,
            "repo_id": "owner/repo",
            "full_name": "Owner/Repo",
            "period": "daily",
            "observed_date": "2026-01-01",
            "captured_at": timestamp,
        },
        "github_repo_recommendations": {
            "repo_id": "owner/repo",
            "active": True,
            "recommended_at": timestamp,
            "updated_at": timestamp,
        },
        "github_project_semantic_sources": {
            "repo_id": "owner/repo",
            "readme_sha256": "",
            "readme_etag": "",
            "readme_status": "pending",
            "readme_retry_count": 0,
            "source_fingerprint": "",
            "indexed_fingerprint": "",
            "index_version": "",
            "embedding_provider": "",
            "embedding_model": "",
            "embedding_dimension": 0,
            "chunk_count": 0,
            "index_status": "pending",
            "index_retry_count": 0,
        },
        "tool_websites": {
            "id": 103,
            "canonical_url": "https://example.test/tool",
            "normalized_url_hash": "b" * 64,
            "domain": "example.test",
            "title": "Tool",
            "image_url": "",
            "fetch_status": "succeeded",
            "source_fingerprint": fingerprint,
            "visibility": "public",
        },
        "tool_website_enrichments": {
            "website_id": 103,
            "category_slug": "agents",
            "category_name": "Agents",
            "subcategory_slug": "",
            "subcategory_name": "",
            "description_zh": "测试",
            "confidence": 1.0,
            "source_fingerprint": fingerprint,
            "prompt_version": "v1",
            "model_provider": "test",
            "model_name": "test",
            "status": "succeeded",
        },
        "project_favorites": {
            "id": 104,
            "user_id": 7,
            "project_source": "github",
            "project_id": "owner/repo",
            "created_at": timestamp,
        },
        "user_tool_websites": {
            "id": 105,
            "user_id": 7,
            "website_id": 103,
            "added_via": "manual",
            "created_at": timestamp,
            "updated_at": timestamp,
        },
        "user_tool_website_overrides": {
            "id": 106,
            "user_id": 7,
            "website_id": 103,
            "title": "",
            "image_url": "",
            "description_zh": "",
            "category_slug": "",
            "category_name": "",
            "subcategory_slug": "",
            "subcategory_name": "",
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    }


def test_live_full_catalog_batch_write_persists_and_repairs_sequences() -> None:
    dsn = _test_dsn()
    schema = f"catalog_transfer_it_{uuid.uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    scoped_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
    database = PostgresDatabaseLifecycle(
        lambda: ConnectionPool(
            conninfo=scoped_dsn,
            min_size=1,
            max_size=2,
            timeout=10,
            kwargs={"autocommit": False, "row_factory": dict_row},
            open=False,
        )
    )
    job_id = f"catalog-transfer-{uuid.uuid4().hex}"
    rows = _rows()
    try:
        applied = PostgresMigrationRunner(database).apply()
        assert [migration.version for migration in applied] == [1, 2, 3, 4, 5]
        assert set(rows) == {spec.name for spec in TABLE_TRANSFER_SPECS}

        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO project_catalog_migration_runs
                    (job_id, source_identity_sha256, target_database, target_schema,
                     schema_version, mode, options_json, status)
                VALUES (%s, %s, current_database(), %s, 2, 'load', '{}'::jsonb, 'running')
                """,
                (job_id, "0" * 64, schema),
            )
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO project_catalog_migration_checkpoints (job_id, table_name, status)
                    VALUES (%s, %s, 'pending')
                    """,
                    [(job_id, spec.name) for spec in TABLE_TRANSFER_SPECS],
                )

        service = ProjectCatalogTransferService(
            mysql=object(),
            postgres=database,
            config=SimpleNamespace(),
        )
        checkpoint = TableCheckpoint({}, 0, 0, "pending")
        with database.connection() as connection:
            for spec in TABLE_TRANSFER_SPECS:
                written = service._write_table_batch(
                    connection,
                    spec=spec,
                    job_id=job_id,
                    checkpoint=checkpoint,
                    rows=[rows[spec.name]],
                )
                assert written.rows_processed == 1
            repairs = service._repair_identity_sequences(connection)

        assert {repair["table"] for repair in repairs} == {
            "github_repo_snapshots",
            "github_trending_hits",
            "tool_websites",
            "project_favorites",
            "user_tool_websites",
            "user_tool_website_overrides",
        }

        # A separate physical connection proves each low-level batch transaction committed.
        with psycopg.connect(scoped_dsn, row_factory=dict_row) as fresh:
            for spec in TABLE_TRANSFER_SPECS:
                count = fresh.execute(
                    sql.SQL("SELECT COUNT(*) AS count FROM {}").format(
                        sql.Identifier(spec.name)
                    )
                ).fetchone()
                assert count["count"] == 1

            checkpoints = fresh.execute(
                """
                SELECT table_name, rows_processed, batches_processed, status
                FROM project_catalog_migration_checkpoints
                WHERE job_id = %s
                """,
                (job_id,),
            ).fetchall()
            assert len(checkpoints) == 13
            assert all(
                row["rows_processed"] == 1
                and row["batches_processed"] == 1
                and row["status"] == "running"
                for row in checkpoints
            )

            expected_sequences = {
                "github_repo_snapshots_id_seq": 101,
                "github_trending_hits_id_seq": 102,
                "tool_websites_id_seq": 103,
                "project_favorites_id_seq": 104,
                "user_tool_websites_id_seq": 105,
                "user_tool_website_overrides_id_seq": 106,
            }
            for sequence_name, expected_value in expected_sequences.items():
                state = fresh.execute(
                    sql.SQL("SELECT last_value, is_called FROM {}").format(
                        sql.Identifier(sequence_name)
                    )
                ).fetchone()
                assert state == {"last_value": expected_value, "is_called": True}
    finally:
        database.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )
