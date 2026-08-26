-- 海外收单通用配置槽：服务商名（''=未选，fail-closed；'paypal'/'pingpong'
-- 由应用层收口校验，库层不加 CHECK——0051 先例：加新服务商不应强制迁移）、
-- 沙箱开关与三段通用凭证（client_id/client_secret/webhook_secret，语义随
-- 服务商而定：PayPal Client ID·Secret·Webhook ID；PingPong 商户号·签名密钥·
-- 通知盐）。既有行以空串兜底（= 未配置，海外渠道继续 503，fail-closed）。
-- stripe_secret_key/stripe_webhook_secret 两列保留不读（纯增量迁移纪律：
-- 不删既有列、不回写存量行，混合版本部署双向安全）。
ALTER TABLE payment_settings
    ADD COLUMN IF NOT EXISTS overseas_provider TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS overseas_sandbox BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS overseas_client_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS overseas_client_secret TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS overseas_webhook_secret TEXT NOT NULL DEFAULT '';
