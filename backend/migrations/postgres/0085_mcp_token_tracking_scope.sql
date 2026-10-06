-- 存活的 MCP token 追加只读 scope tracking:read，供会员工具 get_my_tracking 使用。
--
-- 设计要点：
--   - 网站 /mcp 与 DSH 向导此前签发的 token 都是同一字面量
--     ["projects:favorites:read"]（应用层 json.dumps 紧凑写法）。只把这一
--     字面量升级为新的默认集合，已连接的客户端不必重建 token 就能调用
--     get_my_tracking；其余写法（显式子集、手工数据）一律不动，也就不存在
--     解析失败让迁移中断的情况。
--   - tracking:read 只读 token 所属用户自己的追踪规则与追踪简报；会员档位仍
--     在每次调用时按 users 实时判定，scope 不等于会员资格。
--   - 只升级仍可认证的行（未吊销、未删除、未过期，与认证 lookup 同口径）；
--     失效 token 的 scope 保持签发时的原样。
--   - 幂等：升级后的字面量不再匹配 WHERE，重复执行为空操作。
UPDATE user_mcp_tokens
SET scopes_json = '["projects:favorites:read","tracking:read"]'
WHERE scopes_json = '["projects:favorites:read"]'
  AND revoked_at IS NULL
  AND deleted_at IS NULL
  AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP);
