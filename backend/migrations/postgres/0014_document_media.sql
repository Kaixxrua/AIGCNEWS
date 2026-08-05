-- 0014: documents 表增加 media 字段，用于存储推文图片/视频/GIF 的 JSON 元数据
ALTER TABLE documents ADD COLUMN media TEXT;

-- 辅助索引：快速定位带媒体的推文（按 source/source_channel 过滤时）
CREATE INDEX idx_documents_media_present ON documents(source, source_channel, (media IS NOT NULL));
