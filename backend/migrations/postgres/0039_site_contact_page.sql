CREATE TABLE IF NOT EXISTS site_contact_page (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    nav_label TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    subtitle TEXT NOT NULL DEFAULT '',
    service_cards JSONB NOT NULL DEFAULT '[]'::jsonb,
    contact_entries JSONB NOT NULL DEFAULT '[]'::jsonb,
    body_markdown TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
