-- 带来源标记的落地计数：MCP 与 /api/v1 的 429 提示链接带 ?ref=…，访问 beacon 上报后
-- 按 (day, source, path) 聚合，同一访客同一天同一来源与落地页只记一次（Redis 去重）。
-- source 与 path 的值域由应用层枚举约束（services/dashboard/landing_sources.py），此处刻意
-- 不加数据库级值域约束：新增来源标记只是统计维度变化，不应触发 schema 迁移。
CREATE TABLE IF NOT EXISTS site_landing_days (
    day DATE NOT NULL,
    source TEXT NOT NULL,
    path TEXT NOT NULL,
    landings BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (day, source, path)
);
