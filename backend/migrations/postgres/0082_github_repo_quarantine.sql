-- 疑似诱饵仓库隔离名单：名单里的仓库不上热榜、不进公开项目库（列表、搜索、计数、速览、MCP）。
-- 每轮热度指标计算后按两条规则整体重算（见 PostgresGitHubProjectIngestionRepository.refresh_github_quarantine）：
--   coordinated_surge  任一天刷星嫌疑分 >= 0.8 且带 coordinated_creation 信号；
--   name_reuse         同名仓库出现在 >= 3 个账号、GitHub 已删掉其中至少 2 个且占一半以上，
--                      第一个被删副本建仓当天及之后建的同名仓库。
-- 候选行删除时随之删除；只存仓库主键与命中规则，不改动候选、富化与指标数据。
CREATE TABLE IF NOT EXISTS github_repo_quarantine (
    repo_id VARCHAR(255) PRIMARY KEY REFERENCES github_repo_candidates(repo_id) ON DELETE CASCADE,
    reason VARCHAR(32) NOT NULL CHECK (reason IN ('coordinated_surge', 'name_reuse')),
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
