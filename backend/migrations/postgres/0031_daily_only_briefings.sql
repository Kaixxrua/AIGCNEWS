-- 简报与订阅改为仅日报：移除周报/月报后历史数据归一。
-- 1) user_subscriptions：weekly/monthly 订阅已无内容可派发，归并为 daily；
--    与既有 daily 行冲突的（唯一键 user_id/channel_id/source/frequency）先去重，
--    再对 weekly+monthly 组内重复（同 user_id/channel_id/source）仅留一行，随后
--    收紧 CHECK 约束为仅 daily。
-- 2) briefing_subscriptions：period 列保留但只允许 daily，非 daily 行同样冲突去重后归并。
-- 3) briefings.date：周报/月报缓存行已无读取入口，直接删除；日报缓存键去掉
--    "_daily" 后缀（新键格式为 "<date>" / "<date>_<source>"）。
-- 4) push_deliveries.item_key：与 briefings.date 同步去后缀，保持幂等记录连续。

DELETE FROM user_subscriptions us
USING user_subscriptions daily
WHERE us.frequency IN ('weekly', 'monthly')
  AND daily.frequency = 'daily'
  AND daily.user_id = us.user_id
  AND daily.channel_id = us.channel_id
  AND daily.source = us.source;

-- 同一 (user_id, channel_id, source) 下 weekly 与 monthly 并存时，归并前仅保留 id 最大的一行，
-- 避免 UPDATE 后撞上 uq_user_subscriptions_user_channel_source。
DELETE FROM user_subscriptions us
USING user_subscriptions other
WHERE us.frequency IN ('weekly', 'monthly')
  AND other.frequency IN ('weekly', 'monthly')
  AND other.user_id = us.user_id
  AND other.channel_id = us.channel_id
  AND other.source = us.source
  AND other.id > us.id;

UPDATE user_subscriptions
SET frequency = 'daily', updated_at = CURRENT_TIMESTAMP
WHERE frequency IN ('weekly', 'monthly');

ALTER TABLE user_subscriptions DROP CONSTRAINT ck_user_subscriptions_frequency;
ALTER TABLE user_subscriptions ADD CONSTRAINT ck_user_subscriptions_frequency
    CHECK (frequency IN ('daily'));

DELETE FROM briefing_subscriptions bs
USING briefing_subscriptions daily
WHERE bs.period <> 'daily'
  AND daily.period = 'daily'
  AND daily.user_id = bs.user_id
  AND daily.source = bs.source;

-- 同一 (user_id, source) 下多条非 daily 记录并存时仅留一行，避免撞上 uq_sub_user_source_period。
DELETE FROM briefing_subscriptions bs
USING briefing_subscriptions other
WHERE bs.period <> 'daily'
  AND other.period <> 'daily'
  AND other.user_id = bs.user_id
  AND other.source = bs.source
  AND other.id > bs.id;

UPDATE briefing_subscriptions
SET period = 'daily', updated_at = CURRENT_TIMESTAMP
WHERE period <> 'daily';

DELETE FROM briefings WHERE date ~ '_(weekly|monthly)$';

UPDATE briefings
SET date = regexp_replace(date, '_daily$', '')
WHERE date ~ '_daily$';

DELETE FROM push_deliveries WHERE item_key ~ '_(weekly|monthly)$';

UPDATE push_deliveries
SET item_key = regexp_replace(item_key, '_daily$', '')
WHERE item_key ~ '_daily$';
