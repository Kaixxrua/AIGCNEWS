-- 今日暴涨反作弊（一二层：行为信号 + 跨渠道佐证，仅打标不降权）。
-- 刷星买量可直达 hot_score 榜位而现链路无任何异常检测；新增三列承载判定结果：
--   growth_suspicion_score   0..1 嫌疑分（信号加和封顶，佐证命中清零）
--   growth_suspicion_signals JSON 数组，记录命中的信号名（留痕，供误报复核）
--   growth_corroborated      当日在 HN/news/dailyhot/X 任一渠道有曝光佐证
-- 本期不改排序、不下榜；观察误报率后再议降权（后续 PR）。
-- 幂等（IF NOT EXISTS）：允许运维在统一 apply 前先手工补列以配合代码热重启，
-- 后续 runner 正式 apply 时重放为空操作再登记台账（与 0034/0041 同先例）。
ALTER TABLE github_repo_daily_metrics
  ADD COLUMN IF NOT EXISTS growth_suspicion_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  ADD COLUMN IF NOT EXISTS growth_suspicion_signals TEXT NOT NULL DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS growth_corroborated BOOLEAN NOT NULL DEFAULT FALSE;
