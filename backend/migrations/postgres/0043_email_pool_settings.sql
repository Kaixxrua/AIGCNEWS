-- 邮件池配置（单行覆盖 EMAIL_POOL_JSON env）：entries 为 JSON 数组文本，
-- 元素字段对齐 pool_transport.EmailPoolEntry；凭据明文落库，与
-- smtp_settings.password 同水位，脱敏只发生在 API 投影层。
CREATE TABLE IF NOT EXISTS email_pool_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    entries TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
