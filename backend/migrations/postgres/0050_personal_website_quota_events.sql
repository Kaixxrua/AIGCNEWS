-- 个人网页收藏滚动配额的成功事件账本。
-- 关系表可删除，不能承担历史计数；事件不回填，迁移上线后的新添加才计入。
CREATE TABLE IF NOT EXISTS personal_website_quota_events (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    website_id BIGINT NULL REFERENCES tool_websites(id) ON DELETE SET NULL,
    operation VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT personal_website_quota_events_operation_check
        CHECK (operation IN ('auto', 'manual', 'favorite'))
);

CREATE INDEX IF NOT EXISTS idx_personal_website_quota_events_user_created
    ON personal_website_quota_events (user_id, created_at);
