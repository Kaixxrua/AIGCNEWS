ALTER TABLE push_channels
    ADD COLUMN IF NOT EXISTS provider_key VARCHAR(256),
    ADD COLUMN IF NOT EXISTS display_target VARCHAR(256);

ALTER TABLE push_channels DROP CONSTRAINT IF EXISTS ck_push_channels_type;
ALTER TABLE push_channels ADD CONSTRAINT ck_push_channels_type
    CHECK (channel_type IN ('email', 'webhook', 'discord', 'telegram'));

CREATE UNIQUE INDEX IF NOT EXISTS uq_push_channels_provider_key
    ON push_channels (channel_type, provider_key)
    WHERE provider_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS telegram_link_attempts (
    attempt_id UUID PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    nonce_hash CHAR(64) NOT NULL UNIQUE,
    telegram_chat_id VARCHAR(128),
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    expires_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    channel_id BIGINT REFERENCES push_channels(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_telegram_link_attempt_status
        CHECK (status IN ('pending', 'completed', 'expired'))
);

CREATE INDEX IF NOT EXISTS ix_telegram_link_attempts_user_status
    ON telegram_link_attempts (user_id, status, expires_at);
