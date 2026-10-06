-- 删除会员试用记录表。试用已撤下（不提供会员试用），0084 建的 membership_trials
-- 不再有代码读写，生产上也没有人领过。0084 文件保留：迁移台账要求已应用的版本
-- 保留逐字节相同的本地文件。
--
-- Red 变更策略：
--   - 删表前在同一事务里锁表并确认没有记录；万一有记录就 RAISE EXCEPTION 中止迁移，
--     不记台账，留给人工核对，绝不静默删数据。
--   - 删表会连带删掉指向 users 的外键，需要短暂锁住 users。lock_timeout 只在本迁移
--     事务内生效：拿不到锁就失败回滚，不切换服务，也不会长时间排队挡住线上对 users
--     的读写。
--   - 兼容仍在运行的旧版本：现行版本已没有试用代码。
SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    remaining BIGINT;
BEGIN
    IF to_regclass('membership_trials') IS NOT NULL THEN
        LOCK TABLE membership_trials IN ACCESS EXCLUSIVE MODE;
        SELECT count(*) INTO remaining FROM membership_trials;
        IF remaining > 0 THEN
            RAISE EXCEPTION 'migration 0087 aborted: membership_trials 仍有 % 行记录，请先人工核对后再删表', remaining;
        END IF;
    END IF;
END
$$;

DROP TABLE IF EXISTS membership_trials;
