-- 论文作者与 arXiv 标识列：authors 为 JSON-TEXT 字符串数组（沿用 tags 的
-- TEXT + JSON 先例，兼容 upsert 的 COALESCE(NULLIF(...,'')) 合并语义）。
-- 幂等（IF NOT EXISTS），与 0034 一致：允许运维在统一 apply 前先手工补列
-- 以配合代码热重启，后续 runner 正式 apply 时重放为空操作再登记台账。
ALTER TABLE documents ADD COLUMN IF NOT EXISTS authors TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS arxiv_id TEXT;
