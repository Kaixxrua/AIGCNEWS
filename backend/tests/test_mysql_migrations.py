from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend.app.core.mysql_migrations import (
    MySQLMigrationError,
    discover_mysql_migrations,
    split_mysql_statements,
)


def write_migration(directory: Path, name: str, sql: str = "SELECT 1;") -> Path:
    path = directory / name
    path.write_text(sql, encoding="utf-8")
    return path


def test_discover_mysql_migrations_orders_and_hashes(tmp_path: Path) -> None:
    write_migration(tmp_path, "0002_second.sql", "SELECT 2;\n")
    first = write_migration(tmp_path, "0001_first.sql", "SELECT 1;\n")
    migrations = discover_mysql_migrations(tmp_path)
    assert [migration.version for migration in migrations] == [1, 2]
    assert migrations[0].checksum == hashlib.sha256(first.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "filenames",
    [
        ["1_bad.sql"],
        ["0002_second.sql"],
        ["0001_first.sql", "0003_third.sql"],
        ["0001_first.sql", "0001_again.sql"],
    ],
)
def test_discover_rejects_invalid_duplicate_or_gapped_files(
    tmp_path: Path, filenames: list[str]
) -> None:
    for filename in filenames:
        write_migration(tmp_path, filename)
    with pytest.raises(MySQLMigrationError):
        discover_mysql_migrations(tmp_path)


def test_outbox_migration_is_key_only_and_indexed_for_claiming() -> None:
    migration = discover_mysql_migrations()[0]
    lowered = migration.sql.lower()
    assert migration.filename == "0001_project_catalog_outbox.sql"
    assert "create table if not exists project_catalog_outbox" in lowered
    assert "event_id char(36) not null" in lowered
    assert "aggregate_key varchar(1024) not null" in lowered
    assert "idx_project_catalog_outbox_claim" in lowered
    assert "lease_token char(36)" in lowered
    assert "readme_text" not in lowered
    assert "description text" not in lowered
    assert "password" not in lowered


def test_daily_growth_backfill_records_keys_before_updating_rows() -> None:
    migration = discover_mysql_migrations()[1]
    statements = split_mysql_statements(migration.sql)

    assert migration.filename == "0002_daily_growth_source_outbox.sql"
    assert len(statements) == 2
    assert statements[0].startswith("INSERT INTO project_catalog_outbox")
    assert "JSON_OBJECT('metric_date', metric_date, 'repo_id', repo_id)" in statements[0]
    assert "mysql_migration_daily_growth_source_backfill" in statements[0]
    assert statements[1].startswith("UPDATE github_repo_daily_metrics")
    assert "daily_growth_source = 'snapshot_delta'" in statements[1]


def test_statement_splitter_preserves_semicolons_inside_strings() -> None:
    assert split_mysql_statements("SELECT 'a;b'; -- comment\nSELECT `x`; # tail") == [
        "SELECT 'a;b'",
        "SELECT `x`",
    ]
    assert split_mysql_statements("SELECT 5--2;") == ["SELECT 5--2"]
    assert split_mysql_statements("SELECT/**/1;") == ["SELECT 1"]
