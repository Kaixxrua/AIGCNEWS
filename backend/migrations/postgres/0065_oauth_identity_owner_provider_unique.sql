-- Account settings expose each provider as connected or unconnected. Enforce
-- that one account cannot accumulate multiple subjects for the same provider.
-- Fail closed instead of deleting an existing login identity implicitly.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM user_oauth_identities
        GROUP BY user_id, provider
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'duplicate OAuth identities exist for the same user and provider';
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_user_oauth_identity_user_provider
    ON user_oauth_identities (user_id, provider);
