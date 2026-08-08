-- 用户外键统一：github_repo_recommendations.recommended_by_user_id、
-- project_favorites.user_id、user_tool_websites.user_id、
-- user_tool_website_overrides.user_id 在 0001 中建为 BIGINT 且无 REFERENCES，
-- 而 users.id 是 INTEGER，类型不一致且删除用户会留下孤儿行。
--
-- Red 变更策略：先在 DO 块内做数据校验（孤儿行 / 超出 INTEGER 范围的值），
-- 任一表不满足即 RAISE EXCEPTION 中止迁移并给出明确错误，绝不静默截断；
-- 校验通过后才统一类型为 INTEGER 并补 ON DELETE CASCADE 外键。
-- 注意：recommended_by_user_id 可空，删除推荐人时其推荐记录随行级联删除
-- （与项目「用户删除即清理其全部行」口径一致）；NULL 值本身不参与校验。
--
-- 范围说明：tool_websites.added_by_user_id 同为 BIGINT 无 REFERENCES，
-- 属于松散归属标记而非所有权边，本迁移不处理，留待后续单独评估。

DO $$
DECLARE
    bad_count BIGINT;
BEGIN
    SELECT COUNT(*) INTO bad_count
    FROM github_repo_recommendations r
    WHERE r.recommended_by_user_id IS NOT NULL
      AND (r.recommended_by_user_id > 2147483647
           OR r.recommended_by_user_id < -2147483648
           OR NOT EXISTS (SELECT 1 FROM users u WHERE u.id = r.recommended_by_user_id));
    IF bad_count > 0 THEN
        RAISE EXCEPTION 'migration 0030 aborted: github_repo_recommendations 存在 % 行 recommended_by_user_id 孤儿或超出 INTEGER 范围的记录，请先人工核对清理后再执行迁移', bad_count;
    END IF;

    SELECT COUNT(*) INTO bad_count
    FROM project_favorites f
    WHERE f.user_id > 2147483647
       OR f.user_id < -2147483648
       OR NOT EXISTS (SELECT 1 FROM users u WHERE u.id = f.user_id);
    IF bad_count > 0 THEN
        RAISE EXCEPTION 'migration 0030 aborted: project_favorites 存在 % 行 user_id 孤儿或超出 INTEGER 范围的记录，请先人工核对清理后再执行迁移', bad_count;
    END IF;

    SELECT COUNT(*) INTO bad_count
    FROM user_tool_websites w
    WHERE w.user_id > 2147483647
       OR w.user_id < -2147483648
       OR NOT EXISTS (SELECT 1 FROM users u WHERE u.id = w.user_id);
    IF bad_count > 0 THEN
        RAISE EXCEPTION 'migration 0030 aborted: user_tool_websites 存在 % 行 user_id 孤儿或超出 INTEGER 范围的记录，请先人工核对清理后再执行迁移', bad_count;
    END IF;

    SELECT COUNT(*) INTO bad_count
    FROM user_tool_website_overrides o
    WHERE o.user_id > 2147483647
       OR o.user_id < -2147483648
       OR NOT EXISTS (SELECT 1 FROM users u WHERE u.id = o.user_id);
    IF bad_count > 0 THEN
        RAISE EXCEPTION 'migration 0030 aborted: user_tool_website_overrides 存在 % 行 user_id 孤儿或超出 INTEGER 范围的记录，请先人工核对清理后再执行迁移', bad_count;
    END IF;
END $$;

ALTER TABLE github_repo_recommendations
    ALTER COLUMN recommended_by_user_id TYPE INTEGER;
ALTER TABLE github_repo_recommendations
    ADD CONSTRAINT fk_gh_repo_recommendations_user
    FOREIGN KEY (recommended_by_user_id) REFERENCES users(id) ON DELETE CASCADE;

ALTER TABLE project_favorites
    ALTER COLUMN user_id TYPE INTEGER;
ALTER TABLE project_favorites
    ADD CONSTRAINT fk_project_favorites_user
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

ALTER TABLE user_tool_websites
    ALTER COLUMN user_id TYPE INTEGER;
ALTER TABLE user_tool_websites
    ADD CONSTRAINT fk_user_tool_websites_user
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

ALTER TABLE user_tool_website_overrides
    ALTER COLUMN user_id TYPE INTEGER;
ALTER TABLE user_tool_website_overrides
    ADD CONSTRAINT fk_user_tool_website_overrides_user
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
