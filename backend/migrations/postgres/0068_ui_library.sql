-- UI library discovery, account likes and atomic daily copy allowances.
CREATE TABLE IF NOT EXISTS ui_discovery_sources (
    source_id TEXT PRIMARY KEY,
    revision TEXT,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_success_at TIMESTAMPTZ,
    error TEXT
);
CREATE TABLE IF NOT EXISTS ui_discovery_candidates (
    candidate_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    payload JSONB NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_kind TEXT NOT NULL CHECK (change_kind IN ('baseline', 'new', 'updated')),
    review_status TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS ix_ui_candidates_updated ON ui_discovery_candidates(updated_at DESC);
CREATE TABLE IF NOT EXISTS ui_template_likes (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    template_id TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    first_liked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(user_id, template_id)
);
CREATE INDEX IF NOT EXISTS ix_ui_likes_window ON ui_template_likes(first_liked_at, template_id) WHERE active;
CREATE TABLE IF NOT EXISTS ui_copy_daily_usage (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    usage_date DATE NOT NULL,
    used INTEGER NOT NULL DEFAULT 0 CHECK (used >= 0),
    PRIMARY KEY(user_id, usage_date)
);
CREATE TABLE IF NOT EXISTS ui_copy_receipts (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request_id UUID NOT NULL,
    template_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('source', 'prompt')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(user_id, request_id)
);
