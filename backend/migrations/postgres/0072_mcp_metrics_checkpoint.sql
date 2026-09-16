-- Redis remains the live read/write path; this singleton is a durable recovery checkpoint.
CREATE TABLE mcp_metrics_checkpoint (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    total_calls BIGINT NOT NULL CHECK (total_calls >= 0),
    dsh_calls BIGINT NOT NULL CHECK (dsh_calls >= 0 AND dsh_calls <= total_calls),
    snapshot JSONB NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
