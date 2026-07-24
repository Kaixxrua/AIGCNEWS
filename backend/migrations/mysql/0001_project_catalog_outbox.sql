CREATE TABLE IF NOT EXISTS project_catalog_outbox (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    event_id CHAR(36) NOT NULL,
    aggregate_type VARCHAR(64) NOT NULL,
    aggregate_key VARCHAR(1024) NOT NULL,
    operation VARCHAR(16) NOT NULL,
    source_method VARCHAR(128) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempt_count INT NOT NULL DEFAULT 0,
    available_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    lease_token CHAR(36),
    lease_expires_at DATETIME(6),
    processed_at DATETIME(6),
    last_error_code VARCHAR(128),
    last_error_summary VARCHAR(255),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_project_catalog_outbox_event_id UNIQUE (event_id),
    CONSTRAINT ck_project_catalog_outbox_operation
        CHECK (operation IN ('reconcile', 'delete')),
    CONSTRAINT ck_project_catalog_outbox_status
        CHECK (status IN ('pending', 'leased', 'retry', 'processed', 'dead')),
    INDEX idx_project_catalog_outbox_claim
        (status, available_at, lease_expires_at, id),
    INDEX idx_project_catalog_outbox_aggregate
        (aggregate_type, aggregate_key(512), id),
    INDEX idx_project_catalog_outbox_lease (lease_token)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
