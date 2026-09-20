ALTER TABLE ai_ops_config ADD COLUMN recovery_enabled BOOLEAN NOT NULL DEFAULT TRUE;
CREATE TABLE ai_ops_recovery_actions (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    task_id INTEGER NOT NULL UNIQUE,
    job_id TEXT NOT NULL CHECK (job_id IN ('news_techmeme', 'hackernews', 'dailyhot_hotlists')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL CHECK (status IN ('reserved', 'scheduled', 'uncertain'))
);
CREATE INDEX ai_ops_recovery_recent ON ai_ops_recovery_actions (created_at DESC);
