-- 简报缓存按日期幂等：同一天（含来源后缀）只允许一行。
-- save_briefing 原先是裸 INSERT，调度重启、人工补跑或强制重新生成同一期
-- 都会写入重复行，读取端只能靠 ORDER BY id DESC 掩盖；先去重（每个 date
-- 保留 id 最大的最新行），再加唯一索引，仓储层随之改为 ON CONFLICT upsert。
-- 注意：briefing_subscriptions.last_delivered_briefing_id 记录的是简报 id，
-- 被删除的都是被更新的行取代的旧 id，不影响「已投递到 id X」的单调语义。
DELETE FROM briefings b
USING briefings newer
WHERE b.date = newer.date
  AND newer.id > b.id;

CREATE UNIQUE INDEX uq_briefings_date
    ON briefings (date);
