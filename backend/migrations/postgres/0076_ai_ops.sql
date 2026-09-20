CREATE TABLE IF NOT EXISTS ai_ops_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    interval_minutes INTEGER NOT NULL DEFAULT 15 CHECK (interval_minutes BETWEEN 5 AND 120)
);
INSERT INTO ai_ops_config (id) VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS ai_ops_runs (
    id UUID PRIMARY KEY,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'cancelled', 'interrupted')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    events JSONB NOT NULL DEFAULT '[]',
    report TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS ai_ops_one_active ON ai_ops_runs ((status)) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS ai_ops_recent ON ai_ops_runs (started_at DESC);
