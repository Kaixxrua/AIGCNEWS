-- 会员到期时间：与 membership_tier（0045）同构直接挂 users 列。
-- NULL = 长期有效；非空时由应用层 resolve_effective_tier 在读取侧判定，
-- 过期 member 按 free 处理（fail-closed，无需后台任务回写档位）。
-- 不加 CHECK/默认值约束，保持与 0045 相同的幂等迁移先例。
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS membership_expires_at TIMESTAMPTZ NULL;
