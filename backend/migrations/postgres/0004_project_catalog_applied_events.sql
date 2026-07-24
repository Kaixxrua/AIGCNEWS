CREATE TABLE project_catalog_applied_events (
    event_id UUID PRIMARY KEY,
    outbox_id BIGINT NOT NULL,
    aggregate_type VARCHAR(64) NOT NULL,
    aggregate_key JSONB NOT NULL,
    operation VARCHAR(16) NOT NULL,
    source_method VARCHAR(128) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_project_catalog_applied_events_operation
        CHECK (operation IN ('reconcile', 'delete'))
);

CREATE INDEX idx_project_catalog_applied_events_outbox_id
    ON project_catalog_applied_events (outbox_id);

CREATE INDEX idx_project_catalog_applied_events_applied_at
    ON project_catalog_applied_events (applied_at);
