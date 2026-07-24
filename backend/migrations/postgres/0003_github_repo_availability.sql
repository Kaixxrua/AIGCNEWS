ALTER TABLE github_repo_candidates
    ADD COLUMN IF NOT EXISTS availability_status VARCHAR(32) NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS not_found_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS availability_checked_at TEXT;

ALTER TABLE github_repo_candidates
    DROP CONSTRAINT IF EXISTS ck_github_repo_candidates_availability_status;

ALTER TABLE github_repo_candidates
    ADD CONSTRAINT ck_github_repo_candidates_availability_status
    CHECK (availability_status IN ('active', 'not_found'));
