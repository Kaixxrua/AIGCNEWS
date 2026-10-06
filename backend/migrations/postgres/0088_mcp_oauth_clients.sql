-- MCP OAuth 登录：远程 MCP 客户端（Claude Code、Claude.ai 等）在本站动态注册
-- （RFC 7591），用户在浏览器里同意授权后换到令牌。令牌仍是 user_mcp_tokens 里的
-- 普通行，Go 侧鉴权查询不变，用户在 /mcp 页面能看到并删除。
--
-- 设计要点：
--   - mcp_oauth_clients 存注册过的客户端：client_id 随机生成；redirect_uris_json 是
--     注册时校验过的回调地址数组。公开客户端（token_endpoint_auth_method = 'none'）
--     不发密钥，只靠 PKCE，MCP 客户端一般这样注册；声明 client_secret_post/basic
--     （RFC 7591 规定没声明时按 basic）才发密钥，库里只存 SHA-256 摘要。两条 CHECK
--     保证方法取值合法、且「有密钥」与「非公开客户端」严格对应。
--   - last_authorized_at 记最近一次成功换到令牌的时间；从未完成授权且注册超过
--     30 天的客户端由注册接口顺手清理。
--   - user_mcp_tokens.oauth_client_id 标记令牌来自哪个 OAuth 客户端：同一用户在同一
--     客户端重新授权时吊销旧令牌，不让令牌越积越多。手动创建与 DSH 令牌为 NULL。
--     刻意不加外键：清理客户端不应连带改动令牌行，令牌由用户在 /mcp 页面删除。
--   - 只加表、加可空列，不改已有数据；旧版本应用不读写这些对象，回退安全。
--   - 给 user_mcp_tokens 加列要短暂拿排他锁。lock_timeout 只在本迁移事务内生效：
--     拿不到锁就失败回滚，不长时间排队挡住线上的令牌鉴权查询。
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS mcp_oauth_clients (
    client_id VARCHAR(64) PRIMARY KEY,
    client_name VARCHAR(128) NOT NULL DEFAULT '',
    redirect_uris_json TEXT NOT NULL,
    token_endpoint_auth_method VARCHAR(32) NOT NULL DEFAULT 'none'
        CHECK (token_endpoint_auth_method IN ('none', 'client_secret_post', 'client_secret_basic')),
    client_secret_hash VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_authorized_at TIMESTAMPTZ,
    CHECK ((token_endpoint_auth_method = 'none') = (client_secret_hash IS NULL))
);

ALTER TABLE user_mcp_tokens
    ADD COLUMN IF NOT EXISTS oauth_client_id VARCHAR(64);
