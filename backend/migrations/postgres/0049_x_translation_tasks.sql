-- X 推文 LLM 翻译任务：外层推文与引用推文同构持久化，支持失败观测与重试。
CREATE TABLE IF NOT EXISTS x_translation_tasks (
    id BIGSERIAL PRIMARY KEY,
    document_id VARCHAR(255) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    target_kind VARCHAR(16) NOT NULL CHECK (target_kind IN ('outer', 'quote')),
    source_tweet_id VARCHAR(255) NOT NULL,
    source_text TEXT NOT NULL,
    source_lang VARCHAR(32) NOT NULL DEFAULT '',
    source_fingerprint CHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (
        status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')
    ),
    skip_reason VARCHAR(64),
    translation_zh TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error TEXT,
    model_provider VARCHAR(64),
    model_name VARCHAR(255),
    prompt_version VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    CONSTRAINT uq_x_translation_tasks_target UNIQUE (document_id, target_kind)
);

CREATE INDEX IF NOT EXISTS idx_x_translation_tasks_status_updated
    ON x_translation_tasks (status, updated_at, id);

CREATE INDEX IF NOT EXISTS idx_x_translation_tasks_retryable
    ON x_translation_tasks (updated_at, id)
    WHERE status IN ('pending', 'failed');

CREATE INDEX IF NOT EXISTS idx_x_translation_tasks_source_tweet
    ON x_translation_tasks (source_tweet_id);
