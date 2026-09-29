-- 滚动 24 小时星增的原始观测：每次写快照同事务追加一行，保留约 3 天。
-- watchers 仅在社区指标完整时记录，其余为 NULL，避免残缺值参与增速计算。
CREATE TABLE IF NOT EXISTS github_repo_star_observations (
    repo_id VARCHAR(255) NOT NULL
        REFERENCES github_repo_candidates(repo_id) ON DELETE CASCADE,
    observed_at TIMESTAMPTZ NOT NULL,
    stars BIGINT NOT NULL CHECK (stars > 0),
    forks BIGINT,
    watchers BIGINT,
    PRIMARY KEY (repo_id, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_gh_star_observations_observed_at
    ON github_repo_star_observations (observed_at);
