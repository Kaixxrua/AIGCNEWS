-- 会员试用：每个账号一次。开通时在同一事务里把 users 的会员档位置为 member、到期时间置为
-- 开通时刻 + 7 天（与付费开通同一组列，读取侧 resolve_effective_tier 统一判定，到期自动回落
-- free）。本表只记「谁在什么时候用过试用」：user_id 主键即「每个账号一次」的唯一约束，
-- 并发重复开通由行锁 + ON CONFLICT DO NOTHING 收口。账号注销时随之删除。
CREATE TABLE IF NOT EXISTS membership_trials (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
