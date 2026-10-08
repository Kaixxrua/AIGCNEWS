-- Small, date-addressed public snapshots. Existing readers/writers are unchanged.
CREATE TABLE IF NOT EXISTS dashboard_new_words (
    snapshot_date DATE PRIMARY KEY,
    items JSONB NOT NULL CHECK (jsonb_typeof(items) = 'array' AND jsonb_array_length(items) <= 2),
    generated_at TIMESTAMPTZ NOT NULL
);
