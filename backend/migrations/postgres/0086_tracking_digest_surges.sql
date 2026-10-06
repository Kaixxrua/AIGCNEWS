-- 追踪简报记下当期的关键词热度飙升（vip 会员权益）。
--
-- 设计要点：
--   - 生成简报时，对会员的每条关键词规则按 24 小时分桶统计最近 8 天的命中数。
--     满足两个条件记一条飙升：最近 24 小时至少 5 条；不少于前 7 天日均的 3 倍，
--     日均不足 1 按 1 算。规则来源当天一条内容都没有的日子视为采集中断，不计入
--     日均。
--   - surges 是 [{query, count, baseline}] 数组，网页和推送都读这一列，投递时
--     不重算。
--   - 只加列：常量默认值在 PostgreSQL 11+ 只改元数据，不重写表。存量简报为空
--     数组；回退到旧版应用时新列被忽略，插入走默认值。
ALTER TABLE tracking_digests
    ADD COLUMN IF NOT EXISTS surges JSONB NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(surges) = 'array');
