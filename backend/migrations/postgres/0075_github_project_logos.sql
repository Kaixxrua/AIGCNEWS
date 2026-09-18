-- Durable, bounded project-owned artwork; account avatars are not logos.
CREATE TABLE IF NOT EXISTS github_project_logos (
    repo_id VARCHAR(255) PRIMARY KEY REFERENCES github_repo_candidates(repo_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('found', 'not_found', 'failed', 'rate_limited')),
    source_url TEXT NOT NULL DEFAULT '',
    content BYTEA,
    content_type TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL DEFAULT '',
    checked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    next_check_at TIMESTAMPTZ NOT NULL,
    CHECK (content IS NULL OR octet_length(content) <= 262144),
    CHECK (content IS NULL OR content_type IN ('image/webp', 'image/svg+xml'))
);
CREATE INDEX IF NOT EXISTS github_project_logos_due ON github_project_logos(next_check_at);
