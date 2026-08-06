-- push_channels.channel_type 放开 webhook（通用 Webhook 渠道）。
-- 约束随取值域变化重建：email 既有行不受影响，webhook 行自此可写入。
ALTER TABLE push_channels DROP CONSTRAINT ck_push_channels_type;
ALTER TABLE push_channels ADD CONSTRAINT ck_push_channels_type
    CHECK (channel_type IN ('email', 'webhook'));
