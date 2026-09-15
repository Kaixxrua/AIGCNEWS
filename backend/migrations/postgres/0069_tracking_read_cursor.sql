-- Account-owned read receipt; only explicitly displayed issues advance this cursor.
ALTER TABLE tracking_settings
    ADD COLUMN IF NOT EXISTS last_read_digest_id BIGINT NOT NULL DEFAULT 0
    CHECK (last_read_digest_id >= 0);

CREATE INDEX IF NOT EXISTS tracking_digests_user_latest_id_idx
    ON tracking_digests (user_id, id DESC);
