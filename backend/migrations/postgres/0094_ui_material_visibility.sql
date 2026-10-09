-- Keep moderation separate from published catalog artifacts so a refresh cannot
-- resurrect a deprecated material. Restoring preserves the latest actor/time.
CREATE TABLE ui_material_visibility (
    material_id TEXT PRIMARY KEY,
    deprecated BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
