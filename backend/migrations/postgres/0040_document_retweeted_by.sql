-- X 纯转贴标注：转贴者 handle（twitter-cli parser 产出的 retweeted_by）落库列。
-- 幂等（IF NOT EXISTS）：允许运维在统一 apply 前先手工补列以配合代码热重启，
-- 后续 runner 正式 apply 时重放为空操作再登记台账（与 0034 link_card 同先例）。
ALTER TABLE documents ADD COLUMN IF NOT EXISTS retweeted_by TEXT;
