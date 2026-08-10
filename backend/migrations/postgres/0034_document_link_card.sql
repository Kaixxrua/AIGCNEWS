-- X 外链预览卡：card.legacy.binding_values 投影的 JSON 落库列（与 quote 同
-- TEXT + JSON 先例）。幂等（IF NOT EXISTS）：允许运维在统一 apply 前先手工
-- 补列以配合代码热重启，后续 runner 正式 apply 时重放为空操作再登记台账。
ALTER TABLE documents ADD COLUMN IF NOT EXISTS link_card TEXT;
