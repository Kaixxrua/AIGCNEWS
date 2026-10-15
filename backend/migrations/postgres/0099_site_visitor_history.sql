-- Browser-based return visits are independent of registration and IP addresses.
-- Existing daily totals cannot reconstruct historical browser identities.
CREATE TABLE site_visitor_tracking (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO site_visitor_tracking (id) VALUES (1);

CREATE TABLE site_visitor_history (
    visitor_hash TEXT PRIMARY KEY CHECK (length(visitor_hash) = 64),
    first_seen_day DATE NOT NULL
);

CREATE TABLE site_visitor_days (
    day DATE NOT NULL,
    visitor_hash TEXT NOT NULL REFERENCES site_visitor_history (visitor_hash),
    PRIMARY KEY (day, visitor_hash)
);
