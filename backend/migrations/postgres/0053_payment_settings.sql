CREATE TABLE IF NOT EXISTS payment_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    order_ttl_minutes INTEGER NOT NULL DEFAULT 30 CHECK (order_ttl_minutes BETWEEN 5 AND 1440),
    public_base_url TEXT NOT NULL DEFAULT '',
    wechat_appid TEXT NOT NULL DEFAULT '',
    wechat_mchid TEXT NOT NULL DEFAULT '',
    wechat_mch_serial_no TEXT NOT NULL DEFAULT '',
    wechat_api_v3_key TEXT NOT NULL DEFAULT '',
    wechat_private_key_pem TEXT NOT NULL DEFAULT '',
    alipay_appid TEXT NOT NULL DEFAULT '',
    alipay_private_key_pem TEXT NOT NULL DEFAULT '',
    alipay_public_key_pem TEXT NOT NULL DEFAULT '',
    stripe_secret_key TEXT NOT NULL DEFAULT '',
    stripe_webhook_secret TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
