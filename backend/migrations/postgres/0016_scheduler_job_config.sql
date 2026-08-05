CREATE TABLE IF NOT EXISTS scheduler_job_config (
    job_id TEXT PRIMARY KEY,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    interval_minutes INTEGER NOT NULL CHECK (interval_minutes > 0),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scheduler_job_config_enabled ON scheduler_job_config(enabled);
