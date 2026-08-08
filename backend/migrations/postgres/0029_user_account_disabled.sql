-- 账号禁用开关：core/auth.py 的 RequireUser 依赖 record["disabled"] 判定，
-- 但 users 表一直没有该列（record.get("disabled") 恒为 None，检查形同虚设）。
-- 补列后仓储 SELECT 带出，禁用账号在下一次请求即按 401 拒绝。
-- 管理端点（禁用/启用操作入口）不在本迁移范围，待后续单独交付。
ALTER TABLE users ADD COLUMN disabled BOOLEAN NOT NULL DEFAULT FALSE;
