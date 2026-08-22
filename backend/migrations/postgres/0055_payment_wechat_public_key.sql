-- 微信支付公钥模式：回调验签改用商户平台一次性下载的「微信支付公钥」
-- （静态配置，避开平台证书下载/轮换的运维复杂度）。两列即公钥 ID 与公钥
-- PEM；既有行以空串兜底（= 未配置，微信渠道继续 503，fail-closed）。
ALTER TABLE payment_settings
    ADD COLUMN IF NOT EXISTS wechat_public_key_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS wechat_public_key_pem TEXT NOT NULL DEFAULT '';
