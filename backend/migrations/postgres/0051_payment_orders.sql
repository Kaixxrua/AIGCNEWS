-- 支付订单：会员订阅收费骨架的核心台账（ADR 0002）。
-- 一单 = 一次会员套餐购买意图；状态机 pending/paid/expired/closed 由应用层
-- services/payments/orders.py 收口，库层不加 CHECK（与 0045/0046 同一先例：
-- PG 无 ADD CONSTRAINT IF NOT EXISTS，幂等迁移优先）。
--   order_no          本站业务单号（M<yyyyMMddHHmmss><user_id%1e6 补零><4 位随机>，
--                     ≤32 字符兼容微信 out_trade_no 上限），全表唯一
--   channel_order_no  渠道侧交易号（回调回填），空串 = 渠道尚未返回
--   idempotency_key   客户端创建幂等键（可选），防双击/重试重复下单
--   callback_payload  最近一次验签通过的回调原始报文（截断 8KB，审计用）
--   grant_expires_at  本单发放后写入的用户会员到期时间（发放审计与补单检测：
--                     status=paid 且本列为 NULL = 已收款未发放，Ops 可重放）
--   expires_at        支付超时时间（创建时 now + payments_order_ttl_minutes），
--                     调度任务据此关单；与 users.membership_expires_at 无关
-- 幂等（IF NOT EXISTS）：与 0042/0045/0046 同一先例，允许先手工建表再由 runner 登记。
CREATE TABLE IF NOT EXISTS payment_orders (
    id BIGSERIAL PRIMARY KEY,
    order_no TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_code TEXT NOT NULL,
    channel TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CNY',
    status TEXT NOT NULL DEFAULT 'pending',
    channel_order_no TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL DEFAULT '',
    callback_payload TEXT NOT NULL DEFAULT '',
    paid_at TIMESTAMPTZ NULL,
    grant_expires_at TIMESTAMPTZ NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_orders_order_no
    ON payment_orders (order_no);

-- 客户端幂等键：仅在提供时强制唯一（部分唯一索引，PG 原生支持幂等创建）
CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_orders_user_idempotency
    ON payment_orders (user_id, idempotency_key)
    WHERE idempotency_key <> '';

-- 用户侧"我的订单"（新到旧）
CREATE INDEX IF NOT EXISTS idx_payment_orders_user_created
    ON payment_orders (user_id, id DESC);

-- 超时关单扫描 + Ops 按状态筛选
CREATE INDEX IF NOT EXISTS idx_payment_orders_status_expires
    ON payment_orders (status, expires_at);
