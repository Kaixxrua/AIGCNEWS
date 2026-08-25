CREATE TABLE IF NOT EXISTS oauth_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled_providers TEXT NOT NULL DEFAULT '',
    public_base_url TEXT NOT NULL DEFAULT '',
    github_client_id TEXT NOT NULL DEFAULT '',
    github_client_secret_envelope TEXT NOT NULL DEFAULT '',
    google_client_id TEXT NOT NULL DEFAULT '',
    google_client_secret_envelope TEXT NOT NULL DEFAULT '',
    wechat_app_id TEXT NOT NULL DEFAULT '',
    wechat_app_secret_envelope TEXT NOT NULL DEFAULT '',
    state_ttl_seconds INTEGER NOT NULL DEFAULT 300
        CHECK (state_ttl_seconds BETWEEN 60 AND 900),
    handoff_ttl_seconds INTEGER NOT NULL DEFAULT 120
        CHECK (handoff_ttl_seconds BETWEEN 30 AND 600),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
