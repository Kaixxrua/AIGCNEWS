# 文档索引

> 规则：文档首次落地时在此登记；退役文档加历史归档横幅并移入「历史归档」组。

## 新人入口

| 文档 | 内容 |
|---|---|
| [project-overview.md](project-overview.md) | 项目全景概述：产品、架构、数据、部署与工程状态 |
| [architecture.md](architecture.md) | 功能架构当前态（数据库：PostgreSQL 16 唯一关系型运行时） |

## 对外接口

| 文档 | 内容 |
|---|---|
| [mcp-server.md](mcp-server.md) | AIGC Radar MCP（旗舰接口）：协议参数、MCP-first 策略、fallback 语义与鉴权 |
| [mcp-registry.md](mcp-registry.md) | AIGC Radar MCP 登记到官方 registry 与目录站的发布手册 |
| [subscriptions.md](subscriptions.md) | 订阅推送：用户订阅与推送渠道的数据模型、API、验证码与凭据加密策略 |
| [dailyhot-source.md](dailyhot-source.md) | DailyHot 聚合热榜源：自托管 DailyHotApi 的部署、配置与验证 |

## 开发规范

| 文档 | 内容 |
|---|---|
| [git-workflow.md](git-workflow.md) | 提交信息格式、PR-sized 工作单元、自动推送约束 |
| [mcp-vs-websearch-agent-project-discovery.md](mcp-vs-websearch-agent-project-discovery.md) | MCP 与 WebSearch 项目搜索对比实测（MCP-first 策略依据） |

## 运维

| 文档 | 内容 |
|---|---|
| [linux-server-boot.md](linux-server-boot.md) | Linux 服务器开机启动（Docker Compose + systemd） |
| [postgres-application-backup-restore.md](postgres-application-backup-restore.md) | PostgreSQL 应用库备份与恢复验收 |
| [mysql-retirement-runbook.md](mysql-retirement-runbook.md) | MySQL 最终退役运行手册（最终操作基线） |
| [project-catalog-cutover-runbook.md](project-catalog-cutover-runbook.md) | 项目目录切换演练手册（历史操作记录） |

## 分析笔记

| 文档 | 内容 |
|---|---|
| [openwork-hot-score-breakdown.md](openwork-hot-score-breakdown.md) | 热度评分 99.18 分解说明（指标算法实例） |
| [interview-project-summary.md](interview-project-summary.md) | 面试答辩项目概括 |

## 历史归档（不得据此实施）

| 文档 | 归档原因 |
|---|---|
| [code-analysis.md](code-analysis.md) | 已由 architecture.md 取代 |
| [database-backend-migration-plan.md](database-backend-migration-plan.md) | 迁移已完成，MySQL 已退役 |
| [system-update-design.md](system-update-design.md) | 2026-03 设计稿，部分内容已实现或失效 |

## 子目录

| 目录 | 内容 |
|---|---|
| [adr/](adr/) | 架构决策记录（Architecture Decision Records）：[0001 JWT 密钥轮换与启动守卫](adr/0001-jwt-secret-rotation-and-startup-guard.md) |
| [api/](api/) | API 专项文档（预留） |
| [prompts/](prompts/) | Prompt 模板与说明（预留） |
