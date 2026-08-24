-- 会员套餐价格覆盖：管理员在监控页运行时调整月付/年付价格，无需改代码发布。
-- plans.py 常量是默认商业承诺；本表只存覆盖值，缺行即按默认价生效。
-- 金额一律整数分（杜绝浮点）；100–1,000,000 分（¥1–¥10,000）的上下界
-- 拦截「把分当元」的录入事故（15900 元 = 1,590,000 分会被拒）。
-- 调价只影响新订单：在途 pending 订单金额以 payment_orders 行内快照为准，
-- 回调验款也是对快照校验，天然免疫运行时调价。
CREATE TABLE IF NOT EXISTS payment_plan_overrides (
    plan_code TEXT PRIMARY KEY,
    amount_cents INTEGER NOT NULL CHECK (amount_cents BETWEEN 100 AND 1000000),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
