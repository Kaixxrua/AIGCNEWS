from __future__ import annotations

from pathlib import Path

from backend.app.core.postgres_migrations import discover_migrations

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "postgres"
RUNTIME_TABLES = {
    "briefing_subscriptions",
    "briefings",
    "chat_attachments",
    "chat_messages",
    "conversations",
    "document_rank_snapshots",
    "documents",
    "ingestion_tasks",
    "mcp_server_configs",
    "rag_evaluations",
    "runtime_provider_settings",
    "user_mcp_tokens",
    "users",
}


def test_postgres_migrations_are_contiguous_and_include_application_runtime() -> None:
    migrations = discover_migrations(MIGRATIONS_DIR)

    assert [migration.version for migration in migrations] == list(
        range(1, migrations[-1].version + 1)
    )
    assert migrations[5].filename == "0006_application_runtime.sql"
    assert migrations[-1].version == 70
    assert migrations[-1].filename == "0070_ui_discovery_source_configs.sql"


def test_ui_discovery_source_config_migration_is_constrained_and_idempotent() -> None:
    sql = (MIGRATIONS_DIR / "0070_ui_discovery_source_configs.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS ui_discovery_source_configs" in sql
    assert "kind IN ('github', 'feed')" in sql
    assert "cardinality(path_patterns) > 0" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ux_ui_discovery_source_configs_github" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ux_ui_discovery_source_configs_feed" in sql


def test_user_mcp_token_dsh_purpose_migration_is_additive_and_idempotent() -> None:
    sql = (MIGRATIONS_DIR / "0064_user_mcp_token_dsh_purpose.sql").read_text(
        encoding="utf-8"
    )

    # DSH 专用 MCP token：仅 additive 补列 + legacy 行按 client_label 一次性
    # 标记（不删除不轮换）；partial unique index 保证每用户至多一个新制活跃
    # DSH token，legacy hash-only 行不纳入；鉴权 lookup 不感知 purpose。
    assert "ADD COLUMN IF NOT EXISTS purpose VARCHAR(32) NOT NULL DEFAULT 'generic'" in sql
    assert "ADD COLUMN IF NOT EXISTS token_encrypted TEXT" in sql
    assert "WHERE purpose = 'generic' AND client_label = 'dsh-aigc-radar'" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_mcp_tokens_dsh_active" in sql
    assert "WHERE purpose = 'dsh' AND token_encrypted IS NOT NULL" in sql


def test_user_feed_tokens_migration_is_idempotent_and_hash_only() -> None:
    sql = (MIGRATIONS_DIR / "0063_user_feed_tokens.sql").read_text(encoding="utf-8")

    # 会员 RSS feed token：独立于 user_mcp_tokens 的凭证域；SHA-256 hash 唯一 +
    # 每用户至多一个活跃 token 的 partial unique index；明文只以 AES-GCM 密封
    # 形态落库（token_encrypted），永不明文列；无 expires_at（永不过期，访问
    # 控制靠 revoked_at/disabled/档位请求时判定）。全量幂等。
    assert "CREATE TABLE IF NOT EXISTS user_feed_tokens" in sql
    assert "REFERENCES users(id) ON DELETE CASCADE" in sql
    assert "token_hash CHAR(64) NOT NULL" in sql
    assert "token_encrypted TEXT NOT NULL" in sql
    assert "uq_user_feed_tokens_active_user" in sql
    assert "WHERE revoked_at IS NULL" in sql
    # 列定义无 expires_at（注释中的设计说明除外）
    assert "\n    expires_at" not in sql


def test_telegram_settings_migration_is_singleton_and_idempotent() -> None:
    sql = (MIGRATIONS_DIR / "0062_telegram_settings.sql").read_text(encoding="utf-8")

    # Monitor 管理的 Telegram 推送配置：singleton 行（id=1 CHECK），secret 只存
    # AES-GCM envelope 列，TTL/超时区间 CHECK 与服务层校验同口径，全量幂等。
    assert "CREATE TABLE IF NOT EXISTS telegram_settings" in sql
    assert "id INTEGER PRIMARY KEY CHECK (id = 1)" in sql
    assert "bot_token_envelope TEXT NOT NULL DEFAULT ''" in sql
    assert "webhook_secret_envelope TEXT NOT NULL DEFAULT ''" in sql
    assert "CHECK (link_ttl_seconds BETWEEN 60 AND 3600)" in sql
    assert "CHECK (request_timeout_seconds BETWEEN 1 AND 30)" in sql
    assert "bot_token TEXT" not in sql.replace("bot_token_envelope", "")


def test_telegram_discord_push_channels_migration_is_additive_and_idempotent() -> None:
    sql = (MIGRATIONS_DIR / "0060_telegram_discord_push_channels.sql").read_text(
        encoding="utf-8"
    )

    # 直投渠道扩展：仅 additive 补列 + 类型约束重建；provider_key 部分唯一索引
    # 防同一 Telegram chat 被跨用户占用；link attempt 只存 nonce 哈希。
    assert "ADD COLUMN IF NOT EXISTS provider_key VARCHAR(256)" in sql
    assert "ADD COLUMN IF NOT EXISTS display_target VARCHAR(256)" in sql
    assert "DROP CONSTRAINT IF EXISTS ck_push_channels_type" in sql
    assert "'discord'" in sql and "'telegram'" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_push_channels_provider_key" in sql
    assert "WHERE provider_key IS NOT NULL" in sql
    assert "CREATE TABLE IF NOT EXISTS telegram_link_attempts" in sql
    assert "nonce_hash CHAR(64) NOT NULL UNIQUE" in sql
    assert "REFERENCES users(id) ON DELETE CASCADE" in sql
    assert "CREATE INDEX IF NOT EXISTS ix_telegram_link_attempts_user_status" in sql


def test_x_translation_task_leases_migration_is_idempotent() -> None:
    sql = (MIGRATIONS_DIR / "0052_x_translation_task_leases.sql").read_text(encoding="utf-8")

    # 租约/认领令牌：IF NOT EXISTS 幂等；status 枚举保持 0049 原有集合不变。
    assert "ADD COLUMN IF NOT EXISTS claim_token VARCHAR(36)" in sql
    assert "ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_x_translation_tasks_running_lease" in sql


def test_payment_orders_migration_is_idempotent_orders_table() -> None:
    sql = (MIGRATIONS_DIR / "0051_payment_orders.sql").read_text(encoding="utf-8")

    # 订单台账表：IF NOT EXISTS 幂等（与 0042/0045/0046 同一先例）；枚举
    # （plan/channel/status）校验在应用层 services/payments 收口，库层不加
    # CHECK/ADD CONSTRAINT（PG 无 ADD CONSTRAINT IF NOT EXISTS 先例语法）。
    assert "CREATE TABLE IF NOT EXISTS payment_orders" in sql
    assert "order_no TEXT NOT NULL" in sql
    assert "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE" in sql
    assert "amount_cents INTEGER NOT NULL" in sql
    assert "status TEXT NOT NULL DEFAULT 'pending'" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_orders_order_no" in sql
    assert "WHERE idempotency_key <> ''" in sql
    assert "idx_payment_orders_user_created" in sql
    assert "idx_payment_orders_status_expires" in sql
    statements = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    assert "CHECK" not in statements
    assert "ADD CONSTRAINT" not in statements


def test_users_membership_expires_at_migration_is_idempotent_add_column() -> None:
    sql = (MIGRATIONS_DIR / "0048_users_membership_expires_at.sql").read_text(
        encoding="utf-8"
    )

    # 与 0045 同一幂等补列先例：TIMESTAMPTZ NULL（NULL = 长期有效），
    # 过期判定在应用层 membership tiers 模块收口，不加 CHECK/默认值约束。
    assert (
        "ALTER TABLE users\n"
        "    ADD COLUMN IF NOT EXISTS membership_expires_at TIMESTAMPTZ NULL;"
    ) in sql
    statements = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    assert "CHECK" not in statements
    assert "ADD CONSTRAINT" not in statements


def test_users_membership_tier_migration_is_idempotent_add_column() -> None:
    sql = (MIGRATIONS_DIR / "0045_users_membership_tier.sql").read_text(
        encoding="utf-8"
    )

    # 与 0034/0035 同一幂等补列先例：IF NOT EXISTS 允许先手工补列配合热重启，
    # runner 重放为空操作再登记台账。不加 CHECK（PG 无 ADD CONSTRAINT IF NOT
    # EXISTS 先例语法），枚举校验在应用层 membership tiers 模块收口。
    assert (
        "ALTER TABLE users\n"
        "    ADD COLUMN IF NOT EXISTS membership_tier TEXT NOT NULL DEFAULT 'free';"
    ) in sql
    statements = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    assert "CHECK" not in statements
    assert "ADD CONSTRAINT" not in statements


def test_error_events_migration_is_idempotent_append_only_table() -> None:
    sql = (MIGRATIONS_DIR / "0037_error_events.sql").read_text(encoding="utf-8")

    # 追加写日志表：identity PK 即分页游标（ORDER BY id DESC），无需二级索引；
    # IF NOT EXISTS 幂等，与 smtp_settings 同一先例。
    assert "CREATE TABLE IF NOT EXISTS error_events" in sql
    assert "id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY" in sql
    assert "occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP" in sql
    assert "message TEXT NOT NULL" in sql
    assert "stack_trace TEXT" in sql


def test_smtp_settings_migration_is_idempotent_singleton_table() -> None:
    sql = (MIGRATIONS_DIR / "0036_smtp_settings.sql").read_text(encoding="utf-8")

    # 单行配置表（x_credentials_bootstrap_state 先例）：id CHECK (id = 1)
    # 约束保证 singleton；IF NOT EXISTS 幂等，runner 重放为空操作再登记台账；
    # 全列 NOT NULL 默认空串，retain/clear 逻辑无 NULL 分支。
    assert "CREATE TABLE IF NOT EXISTS smtp_settings" in sql
    assert "CHECK (id = 1)" in sql


def test_document_authors_migration_is_idempotent_add_column() -> None:
    sql = (MIGRATIONS_DIR / "0035_document_authors.sql").read_text(encoding="utf-8")

    # 与 0034 同一幂等补列先例：authors 存 JSON-TEXT 字符串数组（tags 先例），
    # arxiv_id 为标量；运维可先手工补列配合热重启，runner 重放为空操作再登记台账。
    assert sql.count("ADD COLUMN IF NOT EXISTS") == 2
    assert "ALTER TABLE documents ADD COLUMN IF NOT EXISTS authors TEXT;" in sql
    assert "ALTER TABLE documents ADD COLUMN IF NOT EXISTS arxiv_id TEXT;" in sql


def test_document_link_card_migration_is_idempotent_add_column() -> None:
    sql = (MIGRATIONS_DIR / "0034_document_link_card.sql").read_text(encoding="utf-8")

    # 幂等补列：允许运维在统一 apply 前先手工补列配合热重启，
    # runner 重放为空操作后登记台账（与 quote TEXT + JSON 先例一致）。
    assert "ALTER TABLE documents ADD COLUMN IF NOT EXISTS link_card TEXT;" in sql


def test_briefings_date_unique_migration_dedupes_before_creating_index() -> None:
    sql = (MIGRATIONS_DIR / "0033_briefings_date_unique.sql").read_text(
        encoding="utf-8"
    )

    # 存量重复行必须先于唯一索引清理，否则迁移在脏数据上直接失败；
    # 每个 date 仅保留 id 最大的最新行。
    assert "newer.id > b.id" in sql
    assert sql.index("DELETE FROM briefings") < sql.index(
        "CREATE UNIQUE INDEX uq_briefings_date"
    )


def test_wechat_official_accounts_migration_defines_secret_safe_tables() -> None:
    sql = (MIGRATIONS_DIR / "0013_wechat_official_accounts.sql").read_text(
        encoding="utf-8"
    )

    for table in (
        "wechat_login_attempts",
        "wechat_sessions",
        "wechat_official_accounts",
        "wechat_articles",
    ):
        assert f"CREATE TABLE {table} (" in sql

    assert "CONSTRAINT uq_wechat_sessions_owner UNIQUE (owner_id)" in sql
    assert "CONSTRAINT uq_wechat_official_accounts_owner_fakeid UNIQUE (owner_id, fakeid)" in sql
    assert "CONSTRAINT uq_wechat_articles_account_stable_key UNIQUE" in sql
    assert "account_id," in sql
    assert "stable_article_key" in sql
    assert "encrypted_uuid_cookie TEXT NOT NULL" in sql
    assert "encrypted_uuid_cookie_nonce TEXT NOT NULL" in sql
    assert "encrypted_token TEXT NOT NULL" in sql
    assert "encrypted_token_nonce TEXT NOT NULL" in sql
    assert "encrypted_cookie TEXT NOT NULL" in sql
    assert "encrypted_cookie_nonce TEXT NOT NULL" in sql
    assert "encryption_key_version VARCHAR(64) NOT NULL" in sql
    assert "owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE" in sql
    assert "account_id BIGINT NOT NULL REFERENCES wechat_official_accounts(id) ON DELETE CASCADE" in sql
    assert "ck_wechat_login_attempt_status" in sql
    assert "ck_wechat_session_status" in sql
    assert "ck_wechat_account_sync_status" in sql
    assert "ck_wechat_articles_itemidx" in sql


def test_application_runtime_migration_defines_every_manifest_runtime_table() -> None:
    sql = (MIGRATIONS_DIR / "0006_application_runtime.sql").read_text(
        encoding="utf-8"
    )

    for table in RUNTIME_TABLES:
        assert f"CREATE TABLE {table} (" in sql


def test_x_credentials_migration_defines_runtime_credential_table() -> None:
    sql = (MIGRATIONS_DIR / "0012_x_credentials.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE x_credentials (" in sql
    assert "id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY" in sql
    assert "auth_token TEXT NOT NULL" in sql
    assert "ct0 TEXT NOT NULL" in sql
    assert "enabled BOOLEAN NOT NULL DEFAULT TRUE" in sql
    assert "sort_order INTEGER NOT NULL DEFAULT 0" in sql
    assert "CREATE INDEX idx_x_credentials_enabled" in sql
    assert "ON x_credentials (enabled, sort_order, id)" in sql
    assert "CREATE INDEX idx_x_credentials_status" in sql
    assert "ON x_credentials (last_test_status, last_test_at)" in sql
    assert "CREATE TABLE x_credentials_bootstrap_state (" in sql
    assert "singleton_key INTEGER PRIMARY KEY" in sql


def test_site_contact_page_migration_is_singleton_with_safe_defaults() -> None:
    sql = (MIGRATIONS_DIR / "0039_site_contact_page.sql").read_text(encoding="utf-8")

    # 单例行配置表：CHECK (id = 1) 与 smtp_settings 同一先例；IF NOT EXISTS 幂等。
    # 默认 enabled=FALSE + 全空字段，开源部署开箱不暴露该页。
    assert "CREATE TABLE IF NOT EXISTS site_contact_page" in sql
    assert "id INTEGER PRIMARY KEY CHECK (id = 1)" in sql
    assert "enabled BOOLEAN NOT NULL DEFAULT FALSE" in sql
    assert "service_cards JSONB NOT NULL DEFAULT '[]'::jsonb" in sql
    assert "contact_entries JSONB NOT NULL DEFAULT '[]'::jsonb" in sql
    assert "body_markdown TEXT NOT NULL DEFAULT ''" in sql


def test_application_runtime_migration_preserves_identity_and_domain_constraints() -> None:
    sql = (MIGRATIONS_DIR / "0006_application_runtime.sql").read_text(
        encoding="utf-8"
    )

    assert sql.count("GENERATED BY DEFAULT AS IDENTITY") == 11
    assert "CHECK (role IN ('user', 'admin'))" in sql
    assert "CHECK (scope IN ('global', 'paper'))" in sql
    assert "CHECK (role IN ('user', 'assistant'))" in sql
    assert "CHECK (status IN ('done', 'streaming', 'deleted', 'regenerated'))" in sql
    assert "CHECK (modality IN ('image', 'pdf'))" in sql
    assert "ON DELETE CASCADE" in sql
    assert "ON DELETE SET NULL" in sql
    assert "AUTO_INCREMENT" not in sql
    assert "TINYINT" not in sql
    assert "ENUM(" not in sql
