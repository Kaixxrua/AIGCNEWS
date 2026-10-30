"""闪光工坊（ShinyDesk）激活码 PayPal 收单：游客下单 → PayPal → 授权服务器发码。

与会员收费（services/payments）分表分路由，只复用 PayPal 渠道实现与
/api/payments/callback/overseas_redirect 回调入口（按单号前缀 SD 分流）。
"""
