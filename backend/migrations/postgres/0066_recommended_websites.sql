-- Standalone, explicitly curated websites. Never derive public content from
-- tool_websites or any user's private collection.
CREATE TABLE recommended_websites (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR(120) NOT NULL CHECK (length(btrim(title)) > 0),
    url VARCHAR(2048) NOT NULL UNIQUE,
    description VARCHAR(500) NOT NULL DEFAULT '',
    category VARCHAR(64) NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_recommended_websites_order
    ON recommended_websites (sort_order, created_at DESC, id DESC);
