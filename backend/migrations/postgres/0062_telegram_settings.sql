CREATE TABLE IF NOT EXISTS telegram_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    bot_token_envelope TEXT NOT NULL DEFAULT '',
    bot_username TEXT NOT NULL DEFAULT '',
    webhook_secret_envelope TEXT NOT NULL DEFAULT '',
    link_ttl_seconds INTEGER NOT NULL DEFAULT 300
        CHECK (link_ttl_seconds BETWEEN 60 AND 3600),
    request_timeout_seconds DOUBLE PRECISION NOT NULL DEFAULT 5.0
        CHECK (request_timeout_seconds BETWEEN 1 AND 30),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
