-- GitHub 项目富化产出英文策展描述（prompt v6 起模型直接产出，随写路径落库）。
-- 此前英文侧只能回落 GitHub 原生 description：存量实测 8.6% 为空或中文为主、
-- 26% 仅一句话；本列承载模型撰写的英文文案，catalog 读路径由 NULL::text 切换为本列。
-- 幂等（IF NOT EXISTS）：允许运维在统一 apply 前先手工补列以配合代码热重启，
-- 后续 runner 正式 apply 时重放为空操作再登记台账（与 0034/0041/0042 同先例）。
ALTER TABLE github_repo_enrichments
  ADD COLUMN IF NOT EXISTS description_en VARCHAR(512) NOT NULL DEFAULT '';
