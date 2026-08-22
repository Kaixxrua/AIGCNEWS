-- 站点访问平台维度计数：beacon 按 User-Agent 归类后按 (day, platform) 聚合。
-- platform 值域由应用层枚举约束（ios/android/windows/macos/other），此处刻意
-- 不加数据库级值域约束：平台桶是展示维度，未来新增桶（如 harmonyos）不应触发 schema 迁移。
CREATE TABLE IF NOT EXISTS site_visit_platform_days (
    day DATE NOT NULL,
    platform TEXT NOT NULL,
    visits BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (day, platform)
);
