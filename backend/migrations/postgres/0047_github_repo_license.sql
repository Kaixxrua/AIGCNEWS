-- 项目 license 捕获：复用决策的合规信号。
-- 编程 agent 在采纳评估时最需要却拿不到 license——没有它，agent 只能推荐
-- 而无法提示 "GPL 传染性 / MIT 可商用" 这类采纳硬约束。本列为 SPDX 标识
-- （MIT、Apache-2.0、GPL-3.0、NOASSERTION 等），空串 = 未声明/未捕获。
-- 回填：随既有 2 小时指标日刷（fetch_github_repo_metrics_batch GraphQL
-- licenseInfo { spdxId }）渐进填充，零额外 API 成本；存量行在下一轮日刷
-- 后自然带值，不做一次性全量回填（避免打爆 GitHub 限流）。
-- 幂等（IF NOT EXISTS）：与 0042/0045/0046 同一先例。
ALTER TABLE github_repo_candidates
    ADD COLUMN IF NOT EXISTS license_spdx_id TEXT NOT NULL DEFAULT '';
