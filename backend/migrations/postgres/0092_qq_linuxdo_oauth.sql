-- Add disabled-by-default provider credentials; all secret values remain sealed.
ALTER TABLE oauth_settings
    ADD COLUMN IF NOT EXISTS qq_client_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS qq_client_secret_envelope TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS linuxdo_client_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS linuxdo_client_secret_envelope TEXT NOT NULL DEFAULT '';

ALTER TABLE user_oauth_identities
    DROP CONSTRAINT IF EXISTS user_oauth_identities_provider_check;
ALTER TABLE user_oauth_identities
    ADD CONSTRAINT user_oauth_identities_provider_check
    CHECK (provider IN ('github', 'google', 'wechat', 'qq', 'linuxdo'));
