-- X 翻译任务租约：隔离过期 worker，避免迟到结果覆盖重新领取后的任务。
ALTER TABLE x_translation_tasks
    ADD COLUMN IF NOT EXISTS claim_token VARCHAR(36),
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_x_translation_tasks_running_lease
    ON x_translation_tasks (lease_expires_at, id)
    WHERE status = 'running';
