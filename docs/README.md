# 文档索引

> 规则：文档首次落地时在此登记；退役文档直接删除并移除登记（历史版本由 git 保留）。

## 新人入口

| 文档 | 内容 |
|---|---|
| [project-overview.md](project-overview.md) | 项目全景：产品定位、数据源全景与逐模块功能走查 |
| [architecture.md](architecture.md) | 架构当前态（开发者向）：分层、API 路由、存储、调度与部署 |

## 对外接口

| 文档 | 内容 |
|---|---|
| [mcp-server.md](mcp-server.md) | AIGC Radar MCP（旗舰接口）：协议参数、MCP-first 策略、fallback 语义与鉴权 |
| [reuse-loop.md](reuse-loop.md) | 复用检查闭环：触发（dsh 插件 / Claude Code hook / MCP instructions）→ 检索 → 采纳回执 → 复用率度量 |
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
| [self-hosting.zh-CN.md](self-hosting.zh-CN.md) | 自托管完整指南（中文）：TLS 证书、SMTP 引导、端口与测试命令 |
| [self-hosting.md](self-hosting.md) | Self-hosting guide (English twin of the above) |
| [linux-server-boot.md](linux-server-boot.md) | Linux 服务器开机启动（Docker Compose + systemd） |
| [postgres-application-backup-restore.md](postgres-application-backup-restore.md) | PostgreSQL 应用库备份与恢复验收 |
| [mysql-retirement-runbook.md](mysql-retirement-runbook.md) | MySQL 最终退役运行手册（最终操作基线） |

## 分析笔记

| 文档 | 内容 |
|---|---|
| [openwork-hot-score-breakdown.md](openwork-hot-score-breakdown.md) | 热度评分 99.18 分解说明（指标算法实例） |
| [interview-project-summary.md](interview-project-summary.md) | 面试答辩项目概括 |

## 子目录

| 目录 | 内容 |
|---|---|
| [adr/](adr/) | 架构决策记录（Architecture Decision Records）：[0001 JWT 密钥轮换与启动守卫](adr/0001-jwt-secret-rotation-and-startup-guard.md) |
| [api/](api/) | API 专项文档（预留） |
| [prompts/](prompts/) | Prompt 模板与说明（预留） |
