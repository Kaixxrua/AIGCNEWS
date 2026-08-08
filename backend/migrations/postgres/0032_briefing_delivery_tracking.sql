-- 订阅简报派发幂等：记录每条订阅最近一次成功投递的简报 id。
-- 每日 08:00 派发任务在简报缓存命中时会重复执行（调度重启、人工补跑等），
-- 没有投递标记会让订阅者同日收到多封相同简报；成功投递后回写该列，
-- 下一次执行只推送给 last_delivered_briefing_id 落后于当期 briefing_id 的订阅。
ALTER TABLE briefing_subscriptions
    ADD COLUMN last_delivered_briefing_id INTEGER;
