-- DSH 专用 MCP token：跨刷新复用需要服务端密封明文回显。
--
-- 设计要点：
--   - purpose 区分通用 token（generic）与 DSH 向导签发的 token（dsh）；
--     历史 DSH 向导 token 以 client_label 一次性标记为 dsh（legacy），
--     不删除、不轮换——用户机器上可能仍在使用，恢复走显式 rotate。
--   - token_encrypted 存 AES-256-GCM 密封信封（独立密钥域
--     dsh_mcp_token_encryption_key），库里永不出现明文；仅 dsh 且
--     已密封的行才能被 ensure 解密回显。
--   - 每用户至多一个「新制」活跃 DSH token：partial unique index 只覆盖
--     有密封材料且未吊销/删除的 dsh 行；legacy hash-only 行不纳入
--     （存量可能重复，且无权阻止用户继续使用旧 token）。
--   - 鉴权查询（token_hash lookup）不感知 purpose：DSH token 与通用
--     token 共用同一 lookup 与实时会员档位判定。
ALTER TABLE user_mcp_tokens
    ADD COLUMN IF NOT EXISTS purpose VARCHAR(32) NOT NULL DEFAULT 'generic';
ALTER TABLE user_mcp_tokens
    ADD COLUMN IF NOT EXISTS token_encrypted TEXT;

UPDATE user_mcp_tokens
SET purpose = 'dsh'
WHERE purpose = 'generic' AND client_label = 'dsh-aigc-radar';

CREATE UNIQUE INDEX IF NOT EXISTS uq_user_mcp_tokens_dsh_active
    ON user_mcp_tokens (user_id)
    WHERE purpose = 'dsh' AND token_encrypted IS NOT NULL
      AND revoked_at IS NULL AND deleted_at IS NULL;
