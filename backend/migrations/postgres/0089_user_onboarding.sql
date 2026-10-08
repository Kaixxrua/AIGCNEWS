-- Additive, compatible with older application versions. A replay never resets
-- the terminal status, so other devices do not start showing the welcome again.
ALTER TABLE users ADD COLUMN onboarding_status TEXT NOT NULL DEFAULT 'unseen'
    CHECK (onboarding_status IN ('unseen', 'skipped', 'completed'));
