-- Administrator-managed sources consumed by the daily UI library discovery job.
CREATE TABLE IF NOT EXISTS ui_discovery_source_configs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
    kind TEXT NOT NULL CHECK (kind IN ('github', 'feed')),
    repository TEXT,
    path_patterns TEXT[] NOT NULL DEFAULT '{}',
    feed_url TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (kind = 'github' AND repository IS NOT NULL AND feed_url IS NULL AND cardinality(path_patterns) > 0)
        OR
        (kind = 'feed' AND feed_url IS NOT NULL AND repository IS NULL AND cardinality(path_patterns) = 0)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ui_discovery_source_configs_github
    ON ui_discovery_source_configs(lower(repository)) WHERE kind = 'github';
CREATE UNIQUE INDEX IF NOT EXISTS ux_ui_discovery_source_configs_feed
    ON ui_discovery_source_configs(lower(feed_url)) WHERE kind = 'feed';
