-- 热度 v8：滚动 24 小时星增。日增（daily_star_growth）仍是自然日口径不变；
-- 这三列记录热度实际使用的窗口，供榜单“+N”展示与复核。可空：窗口起点
-- 不可得（无观测、仓龄超过 7 天且无历史）时为 NULL，展示回退到日增。
ALTER TABLE github_repo_daily_metrics
    ADD COLUMN IF NOT EXISTS rolling_24h_star_growth BIGINT,
    ADD COLUMN IF NOT EXISTS rolling_24h_growth_source VARCHAR(32),
    ADD COLUMN IF NOT EXISTS rolling_24h_observed_at TEXT;
