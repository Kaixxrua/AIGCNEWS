-- 聊天附件上传会话元数据：替代 attachment_service 进程内内存注册表。
-- 与 chat_attachments（会话消息附件档案，BIGINT 自增主键）不同，
-- 本表以附件令牌（UUID 字符串）为主键，服务于上传后短期引用与孤儿对账。
-- created_at/expires_at 为 Unix epoch 秒（DOUBLE PRECISION），与服务层
-- time.time() 时钟语义一致；expires_at = 0 表示不过期。
CREATE TABLE chat_attachment_meta (
    attachment_id VARCHAR(64) PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    attachment_type TEXT NOT NULL CHECK (attachment_type IN ('image', 'pdf')),
    status TEXT NOT NULL DEFAULT 'uploading'
        CHECK (status IN ('uploading', 'processing', 'ready', 'error', 'expired')),
    file_name VARCHAR(255) NOT NULL DEFAULT '',
    mime_type VARCHAR(100) NOT NULL DEFAULT '',
    size_bytes BIGINT NOT NULL DEFAULT 0,
    page_count INTEGER NOT NULL DEFAULT 0,
    text_preview TEXT NOT NULL DEFAULT '',
    storage_path VARCHAR(512),
    error_msg TEXT NOT NULL DEFAULT '',
    created_at DOUBLE PRECISION NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL DEFAULT 0
);

CREATE INDEX idx_chat_attachment_meta_user_created
    ON chat_attachment_meta (user_id, created_at DESC);

-- TTL 清理仅扫描设置过期时间的行（当前为图片附件）。
CREATE INDEX idx_chat_attachment_meta_expiry
    ON chat_attachment_meta (expires_at)
    WHERE expires_at > 0;
