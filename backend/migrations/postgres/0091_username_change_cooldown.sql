-- Existing accounts can rename immediately; only an actual rename starts the cooldown.
ALTER TABLE users ADD COLUMN username_change_available_at TIMESTAMPTZ;
