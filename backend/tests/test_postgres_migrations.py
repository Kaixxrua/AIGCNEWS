from __future__ import annotations

import hashlib
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from backend.app.core.postgres_migrations import (
    MigrationError,
    MigrationStatus,
    PostgresMigrationRunner,
    discover_migrations,
    pending_migration_labels,
)


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self._rows: list[dict[str, Any]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        normalized = " ".join(sql.split())
        self.connection.executions.append((normalized, params))
        if self.connection.fail_sql and self.connection.fail_sql in normalized:
            raise RuntimeError("simulated SQL failure")
        if normalized.startswith("SELECT version, filename, checksum_sha256"):
            self._rows = [dict(row) for row in sorted(self.connection.ledger, key=lambda row: row["version"])]
        elif normalized.startswith("INSERT INTO app_schema_migrations"):
            assert params is not None
            self.connection.ledger.append(
                {"version": params[0], "filename": params[1], "checksum_sha256": params[2]}
            )

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class FakeConnection:
    def __init__(
        self,
        ledger: list[dict[str, Any]] | None = None,
        *,
        fail_sql: str = "",
    ) -> None:
        self.ledger = list(ledger or [])
        self.executions: list[tuple[str, tuple[Any, ...] | None]] = []
        self.transactions: list[str] = []
        self.fail_sql = fail_sql

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.transactions.append("begin")
        try:
            yield
        except BaseException:
            self.transactions.append("rollback")
            raise
        else:
            self.transactions.append("commit")


class FakeDatabase:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection_value = connection

    @contextmanager
    def connection(self) -> Iterator[FakeConnection]:
        yield self.connection_value


def write_migration(directory: Path, name: str, sql: str = "SELECT 1;") -> Path:
    path = directory / name
    path.write_text(sql, encoding="utf-8")
    return path


def test_pending_migration_labels_lists_only_unapplied() -> None:
    class StubRunner:
        def status(self) -> list[MigrationStatus]:
            return [
                MigrationStatus(version=1, filename="0001_a.sql", checksum="", applied=True),
                MigrationStatus(version=2, filename="0002_b.sql", checksum="", applied=False),
                MigrationStatus(version=3, filename="0003_c.sql", checksum="", applied=False),
            ]

    assert pending_migration_labels(StubRunner()) == ["0002_b.sql", "0003_c.sql"]  # type: ignore[arg-type]


def test_discover_orders_and_hashes_migrations(tmp_path: Path) -> None:
    write_migration(tmp_path, "0002_second.sql", "SELECT 2;\n")
    first = write_migration(tmp_path, "0001_first.sql", "SELECT 1;\n")

    migrations = discover_migrations(tmp_path)

    assert [migration.filename for migration in migrations] == ["0001_first.sql", "0002_second.sql"]
    assert migrations[0].checksum == hashlib.sha256(first.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "filenames, message",
    [
        (["1_bad.sql"], "invalid PostgreSQL migration filename"),
        (["0002_second.sql"], "contiguous from 0001"),
        (["0001_first.sql", "0003_third.sql"], "contiguous from 0001"),
        (["0001_first.sql", "0001_again.sql"], "duplicate PostgreSQL migration version"),
    ],
)
def test_discover_rejects_invalid_duplicate_or_gapped_files(
    tmp_path: Path, filenames: list[str], message: str
) -> None:
    for filename in filenames:
        write_migration(tmp_path, filename)

    with pytest.raises(MigrationError, match=message):
        discover_migrations(tmp_path)


def test_apply_locks_creates_ledger_and_applies_each_migration_transactionally(tmp_path: Path) -> None:
    write_migration(tmp_path, "0001_first.sql", "CREATE TABLE first_table (id integer);")
    write_migration(tmp_path, "0002_second.sql", "CREATE TABLE second_table (id integer);")
    connection = FakeConnection()
    runner = PostgresMigrationRunner(FakeDatabase(connection), migrations_dir=tmp_path)  # type: ignore[arg-type]

    applied = runner.apply()

    assert [migration.version for migration in applied] == [1, 2]
    assert [row["version"] for row in connection.ledger] == [1, 2]
    sql = [statement for statement, _ in connection.executions]
    assert sql[0].startswith("SELECT pg_advisory_lock")
    assert "CREATE TABLE IF NOT EXISTS app_schema_migrations" in sql[1]
    assert sql[-1].startswith("SELECT pg_advisory_unlock")
    assert connection.transactions == [
        "begin", "commit",  # lock
        "begin", "commit",  # ledger
        "begin", "commit",  # read applied migrations
        "begin", "commit",  # migration 1 and ledger insert
        "begin", "commit",  # migration 2 and ledger insert
        "begin", "commit",  # unlock
    ]


def test_repeat_apply_is_noop(tmp_path: Path) -> None:
    migration_path = write_migration(tmp_path, "0001_first.sql")
    checksum = hashlib.sha256(migration_path.read_bytes()).hexdigest()
    connection = FakeConnection(
        [{"version": 1, "filename": migration_path.name, "checksum_sha256": checksum}]
    )
    runner = PostgresMigrationRunner(FakeDatabase(connection), migrations_dir=tmp_path)  # type: ignore[arg-type]

    assert runner.apply() == []
    assert sum("INSERT INTO app_schema_migrations" in sql for sql, _ in connection.executions) == 0


def test_failed_migration_rolls_back_and_does_not_record_ledger(tmp_path: Path) -> None:
    write_migration(tmp_path, "0001_first.sql", "CREATE TABLE broken_table (id integer);")
    connection = FakeConnection(fail_sql="CREATE TABLE broken_table")
    runner = PostgresMigrationRunner(FakeDatabase(connection), migrations_dir=tmp_path)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="simulated SQL failure"):
        runner.apply()

    assert connection.ledger == []
    assert "rollback" in connection.transactions
    assert connection.executions[-1][0].startswith("SELECT pg_advisory_unlock")


def test_checksum_drift_is_rejected_and_lock_is_released(tmp_path: Path) -> None:
    migration_path = write_migration(tmp_path, "0001_first.sql", "SELECT 'changed';")
    connection = FakeConnection(
        [{"version": 1, "filename": migration_path.name, "checksum_sha256": "0" * 64}]
    )
    runner = PostgresMigrationRunner(FakeDatabase(connection), migrations_dir=tmp_path)  # type: ignore[arg-type]

    with pytest.raises(MigrationError, match="checksum drift"):
        runner.apply()

    assert connection.executions[-1][0].startswith("SELECT pg_advisory_unlock")


def test_applied_history_gap_and_unknown_version_are_rejected(tmp_path: Path) -> None:
    first = write_migration(tmp_path, "0001_first.sql")
    second = write_migration(tmp_path, "0002_second.sql")
    checksums = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (first, second)
    }
    gap_connection = FakeConnection(
        [{"version": 2, "filename": second.name, "checksum_sha256": checksums[second.name]}]
    )
    with pytest.raises(MigrationError, match="history contains a version gap"):
        PostgresMigrationRunner(
            FakeDatabase(gap_connection), migrations_dir=tmp_path  # type: ignore[arg-type]
        ).status()

    unknown_connection = FakeConnection(
        [
            {"version": 1, "filename": first.name, "checksum_sha256": checksums[first.name]},
            {"version": 2, "filename": second.name, "checksum_sha256": checksums[second.name]},
            {"version": 3, "filename": "0003_missing.sql", "checksum_sha256": "0" * 64},
        ]
    )
    with pytest.raises(MigrationError, match="has no local SQL file"):
        PostgresMigrationRunner(
            FakeDatabase(unknown_connection), migrations_dir=tmp_path  # type: ignore[arg-type]
        ).status()


def test_initial_schema_preserves_mysql_text_search_and_sort_fields() -> None:
    migration = discover_migrations()[0]

    required_tables = {
        "github_repo_candidates",
        "github_repo_aliases",
        "github_repo_enrichments",
        "github_repo_snapshots",
        "github_repo_daily_metrics",
        "github_trending_hits",
        "github_repo_recommendations",
        "github_project_semantic_sources",
        "tool_websites",
        "tool_website_enrichments",
        "project_favorites",
        "user_tool_websites",
        "user_tool_website_overrides",
    }
    for table in required_tables:
        assert f"CREATE TABLE {table}" in migration.sql
    candidate_sql = migration.sql.split("CREATE TABLE github_repo_candidates (", 1)[1].split("\n);", 1)[0]
    enrichment_sql = migration.sql.split("CREATE TABLE github_repo_enrichments (", 1)[1].split("\n);", 1)[0]
    website_sql = migration.sql.split("CREATE TABLE tool_websites (", 1)[1].split("\n);", 1)[0]
    assert "topics_json TEXT" in candidate_sql
    assert "created_at TEXT" in candidate_sql
    assert "pushed_at TEXT" in candidate_sql
    assert "first_seen_at TEXT" in candidate_sql
    assert "last_seen_at TEXT" in candidate_sql
    assert "last_snapshot_at TEXT" in candidate_sql
    assert "tags_json TEXT" in enrichment_sql
    assert "raw_metadata_json TEXT" in website_sql
    assert "recommended_at TIMESTAMPTZ" in migration.sql
    assert "repo_id VARCHAR(255) PRIMARY KEY" in migration.sql
    assert "CREATE UNIQUE INDEX uq_gh_candidates_full_name_ci" in migration.sql
    assert "ON github_repo_candidates (LOWER(full_name))" in migration.sql
    assert "alias_repo_id VARCHAR(255) PRIMARY KEY" in migration.sql
    assert "readme_text TEXT" in migration.sql


def test_bilingual_taxonomy_schema_is_additive_and_backfills_by_slug() -> None:
    migration = discover_migrations()[6]
    assert migration.filename == "0007_bilingual_project_taxonomy.sql"
    for table in (
        "github_repo_enrichments",
        "tool_website_enrichments",
        "user_tool_website_overrides",
    ):
        assert f"ALTER TABLE {table}" in migration.sql
    for column in (
        "category_name_zh", "category_name_en",
        "subcategory_name_zh", "subcategory_name_en",
    ):
        assert migration.sql.count(f"ADD COLUMN {column}") == 3
    assert migration.sql.count("ADD COLUMN description_en") == 2
    assert "project_taxonomy_en_labels" in migration.sql
    assert "WHERE label.slug = enrichment.category_slug" in migration.sql
    assert "WHERE label.slug = enrichment.subcategory_slug" in migration.sql
    assert "description_en = description" not in migration.sql
    assert "description_en = description_zh" not in migration.sql


def test_bilingual_briefing_schema_preserves_legacy_content() -> None:
    migration = discover_migrations()[7]
    assert migration.filename == "0008_bilingual_briefings.sql"
    assert "ALTER TABLE briefings" in migration.sql
    assert "ADD COLUMN content_zh" in migration.sql
    assert "ADD COLUMN content_en" in migration.sql
    assert "UPDATE briefings SET content_zh = content" in migration.sql


def test_bilingual_project_tags_schema_is_additive_and_preserves_legacy_values() -> None:
    migration = discover_migrations()[8]
    assert migration.filename == "0009_bilingual_project_tags.sql"
    for table in ("github_repo_enrichments", "tool_website_enrichments"):
        assert f"ALTER TABLE {table}" in migration.sql
        assert f"UPDATE {table}" in migration.sql
    assert migration.sql.count("ADD COLUMN tags_zh_json TEXT") == 2
    assert migration.sql.count("ADD COLUMN tags_en_json TEXT") == 2
    assert migration.sql.count("SET tags_zh_json = tags_json") == 2
    assert "user_tool_website_overrides" not in migration.sql
    assert "SET tags_en_json" not in migration.sql


def test_daily_hot_v5_default_is_versioned_without_rewriting_history() -> None:
    migration = discover_migrations()[9]
    normalized = " ".join(migration.sql.split())

    assert migration.filename == "0010_github_daily_hot_v5_default.sql"
    assert "ALTER TABLE github_repo_daily_metrics" in normalized
    assert "ALTER COLUMN score_version SET DEFAULT 'daily_hot_v5'" in normalized
    assert "UPDATE" not in migration.sql.upper()
    assert "DROP COLUMN" not in migration.sql.upper()


def test_growth_suspicion_schema_is_additive_and_idempotent() -> None:
    migration = discover_migrations()[41]
    normalized = " ".join(migration.sql.split())

    assert migration.filename == "0042_github_growth_suspicion.sql"
    assert "ALTER TABLE github_repo_daily_metrics" in normalized
    assert "ADD COLUMN IF NOT EXISTS growth_suspicion_score" in normalized
    assert "ADD COLUMN IF NOT EXISTS growth_suspicion_signals" in normalized
    assert "ADD COLUMN IF NOT EXISTS growth_corroborated" in normalized
    assert "UPDATE" not in migration.sql.upper()
    assert "DROP COLUMN" not in migration.sql.upper()


def test_x_watch_accounts_schema_is_additive_and_keys_screen_name() -> None:
    migration = discover_migrations()[10]
    normalized = " ".join(migration.sql.split()).upper()

    assert migration.filename == "0011_x_watch_accounts.sql"
    assert "CREATE TABLE x_watch_accounts" in migration.sql
    assert "CONSTRAINT uq_x_watch_accounts_screen_name UNIQUE (screen_name)" in migration.sql
    assert "enabled BOOLEAN NOT NULL DEFAULT TRUE" in migration.sql
    assert "ALTER TABLE" not in normalized
    assert "DROP" not in normalized
    # UPDATE 语句会以 "UPDATE " 开头出现；列名 UPDATED_AT 不含该片段
    assert "UPDATE " not in normalized


def test_chat_attachment_meta_schema_is_token_keyed_and_additive() -> None:
    migration = discover_migrations()[25]
    normalized = " ".join(migration.sql.split()).upper()

    assert migration.filename == "0026_chat_attachment_meta.sql"
    assert "CREATE TABLE chat_attachment_meta" in migration.sql
    assert "attachment_id VARCHAR(64) PRIMARY KEY" in migration.sql
    assert "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE" in migration.sql
    assert "CHECK (attachment_type IN ('image', 'pdf'))" in migration.sql
    assert "CHECK (status IN ('uploading', 'processing', 'ready', 'error', 'expired'))" in migration.sql
    assert "created_at DOUBLE PRECISION NOT NULL" in migration.sql
    assert "expires_at DOUBLE PRECISION NOT NULL DEFAULT 0" in migration.sql
    assert "storage_path VARCHAR(512)" in migration.sql
    assert "idx_chat_attachment_meta_user_created" in migration.sql
    assert "idx_chat_attachment_meta_expiry" in migration.sql
    assert "WHERE expires_at > 0" in migration.sql
    assert "ALTER TABLE" not in normalized
    assert "DROP" not in normalized
    assert "chat_attachments (" not in migration.sql


def test_transfer_control_schema_is_versioned_and_avoids_sensitive_payloads() -> None:
    migration = discover_migrations()[1]

    assert migration.filename == "0002_project_catalog_transfer_control.sql"
    assert "CREATE TABLE project_catalog_migration_runs" in migration.sql
    assert "CREATE TABLE project_catalog_migration_checkpoints" in migration.sql
    assert "CREATE TABLE project_catalog_migration_failures" in migration.sql
    assert "source_identity_sha256 CHAR(64) NOT NULL" in migration.sql
    assert "cursor_json JSONB NOT NULL" in migration.sql
    assert "last_batch_digest_sha256 CHAR(64)" in migration.sql
    assert "source_prefix_digest_sha256 CHAR(64)" in migration.sql
    assert "password" not in migration.sql.lower()
    assert "readme_text" not in migration.sql.lower()


def test_availability_schema_is_a_separate_versioned_migration() -> None:
    migration = discover_migrations()[2]
    assert migration.filename == "0003_github_repo_availability.sql"
    assert "availability_status VARCHAR(32) NOT NULL DEFAULT 'active'" in migration.sql
    assert "not_found_count INTEGER NOT NULL DEFAULT 0" in migration.sql
    assert "availability_checked_at TEXT" in migration.sql


def test_applied_event_schema_is_versioned_and_key_only() -> None:
    migration = discover_migrations()[3]
    assert migration.filename == "0004_project_catalog_applied_events.sql"
    assert "CREATE TABLE project_catalog_applied_events" in migration.sql
    assert "event_id UUID PRIMARY KEY" in migration.sql
    assert "aggregate_key JSONB NOT NULL" in migration.sql
    assert "idx_project_catalog_applied_events_outbox_id" in migration.sql
    assert "readme_text" not in migration.sql.lower()
    assert "description text" not in migration.sql.lower()


def test_project_catalog_trigram_search_is_versioned_and_transactional() -> None:
    migration = discover_migrations()[4]
    assert migration.filename == "0005_project_catalog_trigram_search.sql"
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in migration.sql
    assert migration.sql.count("USING GIN") == 2
    assert "idx_gh_candidates_lexical_document_trgm" in migration.sql
    assert "idx_gh_enrichments_lexical_document_trgm" in migration.sql
    assert "gin_trgm_ops" in migration.sql
    assert "CONCURRENTLY" not in migration.sql.upper()


def test_conversation_scope_uniqueness_dedupes_before_creating_unique_index() -> None:
    migration = discover_migrations()[27]
    normalized = " ".join(migration.sql.split()).upper()

    assert migration.filename == "0028_conversation_scope_uniqueness.sql"
    # 先去重（消息与附件并入保留行、删除重复会话），再建唯一索引
    assert "UPDATE chat_messages" in migration.sql
    assert "UPDATE chat_attachments" in migration.sql
    assert "DELETE FROM conversations" in migration.sql
    assert "IS NOT DISTINCT FROM" in migration.sql
    assert "CREATE UNIQUE INDEX uq_conv_user_scope_key" in migration.sql
    assert "NULLS NOT DISTINCT" in migration.sql
    assert normalized.index("DELETE FROM CONVERSATIONS") < normalized.index(
        "CREATE UNIQUE INDEX"
    )
    # 去重保留 id 最大行，与仓储层 ORDER BY id DESC LIMIT 1 口径一致
    assert "MAX(id)" in migration.sql


def test_user_account_disabled_schema_is_additive() -> None:
    migration = discover_migrations()[28]
    normalized = " ".join(migration.sql.split()).upper()

    assert migration.filename == "0029_user_account_disabled.sql"
    assert "ALTER TABLE users ADD COLUMN disabled BOOLEAN NOT NULL DEFAULT FALSE" in migration.sql
    assert "DROP" not in normalized
    assert "UPDATE " not in normalized


def test_user_pwd_ver_schema_is_additive() -> None:
    # 口令版本号（AUTH-B）：JWT 声明与库内值逐请求比对，改密即撤销旧 token
    migration = discover_migrations()[40]
    normalized = " ".join(migration.sql.split()).upper()

    assert migration.filename == "0041_user_pwd_ver.sql"
    assert "ALTER TABLE users ADD COLUMN IF NOT EXISTS pwd_ver INTEGER NOT NULL DEFAULT 1" in migration.sql
    assert "DROP" not in normalized
    assert "UPDATE " not in normalized


def test_user_foreign_keys_validate_before_retype_and_add_cascade() -> None:
    migration = discover_migrations()[29]
    normalized = " ".join(migration.sql.split()).upper()

    assert migration.filename == "0030_user_foreign_keys.sql"
    # Red 变更：先校验（孤儿行/超范围即中止），后改类型，最后补外键
    assert "RAISE EXCEPTION" in migration.sql
    assert migration.sql.count("NOT EXISTS (SELECT 1 FROM users u WHERE u.id =") == 4
    assert "2147483647" in migration.sql
    for table, column in (
        ("github_repo_recommendations", "recommended_by_user_id"),
        ("project_favorites", "user_id"),
        ("user_tool_websites", "user_id"),
        ("user_tool_website_overrides", "user_id"),
    ):
        assert f"ALTER TABLE {table}" in migration.sql
        assert f"ALTER COLUMN {column} TYPE INTEGER" in migration.sql
        assert "REFERENCES users(id) ON DELETE CASCADE" in migration.sql
    assert normalized.index("RAISE EXCEPTION") < normalized.index("ALTER COLUMN")
    assert normalized.index("ALTER COLUMN") < normalized.index("ADD CONSTRAINT")
    # recommended_by_user_id 可空：校验必须放过 NULL
    assert "recommended_by_user_id IS NOT NULL" in migration.sql


def test_document_authors_schema_is_additive_and_idempotent() -> None:
    migration = discover_migrations()[34]
    normalized = " ".join(migration.sql.split()).upper()

    assert migration.filename == "0035_document_authors.sql"
    assert migration.sql.count("ADD COLUMN IF NOT EXISTS") == 2
    assert "authors TEXT" in migration.sql
    assert "arxiv_id TEXT" in migration.sql
    assert "DROP" not in normalized
    assert "CONCURRENTLY" not in normalized


def test_site_visit_days_schema_is_additive_and_day_keyed() -> None:
    migration = discover_migrations()[37]
    normalized = " ".join(migration.sql.split()).upper()

    assert migration.filename == "0038_site_visit_days.sql"
    assert "CREATE TABLE IF NOT EXISTS site_visit_days" in migration.sql
    assert "day DATE PRIMARY KEY" in migration.sql
    assert "visits BIGINT NOT NULL DEFAULT 0" in migration.sql
    assert "ALTER TABLE" not in normalized
    assert "DROP" not in normalized
    assert "UPDATE " not in normalized


def test_site_visit_platform_days_schema_is_additive_and_day_platform_keyed() -> None:
    # 平台维度计数表：beacon UA 归类的唯一存储。platform 值域由应用层枚举约束，
    # 刻意不加 CHECK——新增平台桶只是展示维度变化，不应触发 schema 迁移。
    migration = discover_migrations()[53]
    normalized = " ".join(migration.sql.split()).upper()

    assert migration.filename == "0054_site_visit_platform_days.sql"
    assert "CREATE TABLE IF NOT EXISTS site_visit_platform_days" in migration.sql
    assert "PRIMARY KEY (day, platform)" in migration.sql
    assert "visits BIGINT NOT NULL DEFAULT 0" in migration.sql
    assert "ALTER TABLE" not in normalized
    assert "DROP" not in normalized
    assert "UPDATE " not in normalized
    assert "CHECK" not in normalized


def test_payment_wechat_public_key_schema_is_additive() -> None:
    # 微信支付公钥模式：回调验签材料（公钥 ID + 公钥 PEM）随面板/DB 配置面下发，
    # 只加列不动存量——默认空串表示"未配置"，fail-closed 由 provider 侧 7 字段门控。
    # 按文件名定位而非下标：0054 在并行会话中停驻/变动，位置钉法会被牵连。
    migration = next(
        item
        for item in discover_migrations()
        if item.filename == "0055_payment_wechat_public_key.sql"
    )
    normalized = " ".join(migration.sql.split()).upper()

    assert "ALTER TABLE payment_settings" in migration.sql
    assert "ADD COLUMN IF NOT EXISTS wechat_public_key_id TEXT NOT NULL DEFAULT ''" in migration.sql
    assert "ADD COLUMN IF NOT EXISTS wechat_public_key_pem TEXT NOT NULL DEFAULT ''" in migration.sql
    assert "DROP" not in normalized
    assert "UPDATE " not in normalized


def test_payment_plan_overrides_schema_is_additive_and_bounded() -> None:
    # 运行时调价覆盖表：缺行 = plans.py 默认价；CHECK 上下界拦「把分当元」录错。
    # 按文件名定位而非下标：相邻迁移在并行会话中停驻/变动，位置钉法会被牵连。
    migration = next(
        item
        for item in discover_migrations()
        if item.filename == "0056_payment_plan_overrides.sql"
    )
    normalized = " ".join(migration.sql.split()).upper()

    assert "CREATE TABLE IF NOT EXISTS payment_plan_overrides" in migration.sql
    assert "plan_code TEXT PRIMARY KEY" in migration.sql
    assert "amount_cents INTEGER NOT NULL" in migration.sql
    assert "CHECK (amount_cents BETWEEN 100 AND 1000000)" in migration.sql
    assert "ALTER TABLE" not in normalized
    assert "DROP" not in normalized
    assert "UPDATE " not in normalized


def test_live_postgres_apply_twice_and_introspect_schema() -> None:
    dsn = os.getenv("TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is not configured")
    database_name = conninfo_to_dict(dsn).get("dbname", "")
    if "test" not in database_name.casefold():
        pytest.skip("TEST_POSTGRES_DSN database name must contain 'test'")

    schema_name = f"migration_smoke_{uuid.uuid4().hex}"
    connection = psycopg.connect(dsn)

    class DirectDatabase:
        @contextmanager
        def connection(self) -> Iterator[Any]:
            yield connection

    try:
        with connection.transaction():
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
            connection.execute(
                sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema_name))
            )

        runner = PostgresMigrationRunner(DirectDatabase())  # type: ignore[arg-type]
        assert [migration.version for migration in runner.apply()] == list(
            range(1, len(discover_migrations()) + 1)
        )
        assert runner.apply() == []

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                """,
                (schema_name,),
            )
            tables = {row[0] for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = %s
                """,
                (schema_name,),
            )
            indexes = {row[0] for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT constraint_type
                FROM information_schema.table_constraints
                WHERE table_schema = %s
                  AND table_name = 'github_repo_candidates'
                """,
                (schema_name,),
            )
            candidate_constraints = {row[0] for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = 'github_repo_candidates'
                """,
                (schema_name,),
            )
            candidate_columns = {row[0] for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name IN ('github_repo_enrichments', 'tool_website_enrichments')
                  AND column_name IN ('tags_zh_json', 'tags_en_json')
                """,
                (schema_name,),
            )
            bilingual_tag_columns = set(cursor.fetchall())
            cursor.execute(
                """
                SELECT column_default
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = 'github_repo_daily_metrics'
                  AND column_name = 'score_version'
                """,
                (schema_name,),
            )
            score_version_default = cursor.fetchone()[0]

        assert {
            "app_schema_migrations",
            "github_repo_candidates",
            "github_repo_aliases",
            "github_repo_snapshots",
            "github_project_semantic_sources",
            "project_catalog_migration_runs",
            "project_catalog_migration_checkpoints",
            "project_catalog_migration_failures",
            "project_catalog_applied_events",
        } <= tables
        assert {
            "idx_gh_candidates_stars",
            "idx_gh_repo_alias_canonical",
            "idx_gh_snapshots_date_repo",
            "idx_project_semantic_index_status",
            "idx_gh_candidates_lexical_document_trgm",
            "idx_gh_enrichments_lexical_document_trgm",
        } <= indexes
        assert {"PRIMARY KEY", "UNIQUE"} <= candidate_constraints
        assert {
            "availability_status",
            "not_found_count",
            "availability_checked_at",
        } <= candidate_columns
        assert bilingual_tag_columns == {
            ("github_repo_enrichments", "tags_zh_json"),
            ("github_repo_enrichments", "tags_en_json"),
            ("tool_website_enrichments", "tags_zh_json"),
            ("tool_website_enrichments", "tags_en_json"),
        }
        assert score_version_default == "'daily_hot_v5'::character varying"
    finally:
        connection.rollback()
        try:
            with connection.transaction():
                connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(schema_name)
                    )
                )
        finally:
            connection.close()
