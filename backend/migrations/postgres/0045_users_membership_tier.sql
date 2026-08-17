-- 会员档位：1:1 账户属性，与 role/disabled/pwd_ver 同构直接挂 users 列。
-- 不加 CHECK 约束（PG 无 ADD CONSTRAINT IF NOT EXISTS，DO 块会破坏幂等迁移先例），
-- 枚举校验在应用层 services/membership/tiers.py 与授予端点 pydantic Literal。
-- RequireUser 每请求查库读取，授予/吊销下一个请求即生效。
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS membership_tier TEXT NOT NULL DEFAULT 'free';
