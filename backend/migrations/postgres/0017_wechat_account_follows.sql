CREATE TABLE wechat_account_follows (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id BIGINT NOT NULL REFERENCES wechat_official_accounts(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_wechat_account_follows PRIMARY KEY (user_id, account_id)
);

CREATE INDEX idx_wechat_account_follows_account
    ON wechat_account_follows (account_id);
