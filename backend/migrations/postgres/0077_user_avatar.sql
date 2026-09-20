-- Small normalized avatars live with their owner, so backup and deletion remain atomic.
ALTER TABLE users ADD COLUMN avatar_png BYTEA;
ALTER TABLE users ADD COLUMN avatar_digest VARCHAR(64);
ALTER TABLE users ADD CONSTRAINT users_avatar_valid CHECK (
    (avatar_png IS NULL AND avatar_digest IS NULL) OR
    (avatar_png IS NOT NULL AND avatar_digest IS NOT NULL
        AND octet_length(avatar_png) BETWEEN 1 AND 300000
        AND avatar_digest ~ '^[0-9a-f]{64}$')
);
