-- 会话 scope 唯一性：_ensure_conversation 的 SELECT-then-INSERT 在并发下会产生
-- 重复会话（同一 user_id/scope/scope_key 多行），0006 只有非唯一索引无法兜底。
-- 本迁移先对存量重复组内去重：保留 id 最大行（与 _ensure_conversation 的
-- ORDER BY id DESC LIMIT 1 口径一致），其消息与附件并入保留行后再删除重复会话；
-- 最后加 NULLS NOT DISTINCT 唯一索引（scope_key 可空，PostgreSQL 默认把 NULL
-- 视为互不相同，必须显式声明），仓储层 INSERT ... ON CONFLICT 借此兜底竞态。

WITH keepers AS (
    SELECT user_id, scope, scope_key, MAX(id) AS keep_id
    FROM conversations
    GROUP BY user_id, scope, scope_key
),
mapping AS (
    SELECT c.id AS duplicate_id, k.keep_id
    FROM conversations c
    JOIN keepers k
      ON k.user_id = c.user_id
     AND k.scope = c.scope
     AND k.scope_key IS NOT DISTINCT FROM c.scope_key
    WHERE c.id <> k.keep_id
)
UPDATE chat_messages m
SET conversation_id = mapping.keep_id
FROM mapping
WHERE m.conversation_id = mapping.duplicate_id;

WITH keepers AS (
    SELECT user_id, scope, scope_key, MAX(id) AS keep_id
    FROM conversations
    GROUP BY user_id, scope, scope_key
),
mapping AS (
    SELECT c.id AS duplicate_id, k.keep_id
    FROM conversations c
    JOIN keepers k
      ON k.user_id = c.user_id
     AND k.scope = c.scope
     AND k.scope_key IS NOT DISTINCT FROM c.scope_key
    WHERE c.id <> k.keep_id
)
UPDATE chat_attachments a
SET conversation_id = mapping.keep_id
FROM mapping
WHERE a.conversation_id = mapping.duplicate_id;

WITH keepers AS (
    SELECT user_id, scope, scope_key, MAX(id) AS keep_id
    FROM conversations
    GROUP BY user_id, scope, scope_key
),
mapping AS (
    SELECT c.id AS duplicate_id
    FROM conversations c
    JOIN keepers k
      ON k.user_id = c.user_id
     AND k.scope = c.scope
     AND k.scope_key IS NOT DISTINCT FROM c.scope_key
    WHERE c.id <> k.keep_id
)
DELETE FROM conversations c
USING mapping
WHERE c.id = mapping.duplicate_id;

CREATE UNIQUE INDEX uq_conv_user_scope_key
    ON conversations (user_id, scope, scope_key) NULLS NOT DISTINCT;
