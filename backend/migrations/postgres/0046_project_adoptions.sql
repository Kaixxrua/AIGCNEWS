-- 采纳回执：复用检查闭环的最后一环。
-- 触发（MCP 指令/dsh pre-step 注入）与检索（search_github_*_projects）都已上线，
-- 但"用户是否采纳了推荐"此前无任何落库——复用率无从度量，定位叙事无法自证。
-- 本表为仅追加的事实表：每次复用决策（采纳/仅参考/放弃）一行，
-- 由 MCP 工具 submit_project_adoption 或 REST POST /projects/adoptions 写入。
--   project_full_name  决策对象（owner/repo），不强制外键——回执可以针对
--                      本地库尚未收录的项目（fallback 结果），拒绝落库会丢失最真实的信号
--   decision           adopted / reference_only / declined（应用层 Literal 校验，
--                      库层不加 CHECK：PG 无 ADD CONSTRAINT IF NOT EXISTS，与 0045 同先例）
--   reason/query       决策理由与当时检索词（截断落库，供误判与召回质量复核）
--   source             回执来源：mcp / rest / plugin / hook
-- 幂等（IF NOT EXISTS）：与 0042/0045 同一先例，允许先手工建表再由 runner 登记。
CREATE TABLE IF NOT EXISTS project_adoptions (
    id BIGSERIAL PRIMARY KEY,
    project_full_name TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    query TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'mcp',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_project_adoptions_project
    ON project_adoptions (project_full_name);

CREATE INDEX IF NOT EXISTS idx_project_adoptions_created_at
    ON project_adoptions (created_at);
