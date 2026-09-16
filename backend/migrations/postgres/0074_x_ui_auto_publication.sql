-- Explicit opt-in for X-discovered GitHub HTML sources eligible for automatic publication.
ALTER TABLE ui_discovery_source_configs
    ADD COLUMN IF NOT EXISTS x_auto_publish BOOLEAN NOT NULL DEFAULT FALSE;

