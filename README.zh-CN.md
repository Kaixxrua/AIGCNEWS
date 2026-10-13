<div align="center">
  <img src="frontend/public/assets/comic/aigc-news-wordmark.webp" alt="AIGCNEWS" width="440">
</div>

<p align="center">
  <strong>简体中文</strong> · <a href="README.md">English</a>
</p>

<p align="center">
  <a href="https://aigcnews.cn/">在线体验</a> ·
  <a href="https://aigcnews.cn/projects">项目库</a> ·
  <a href="https://aigcnews.cn/ui-library">UI 灵感库</a> ·
  <a href="https://aigcnews.cn/mcp">MCP 接入</a> ·
  <a href="docs/README.md">文档</a>
</p>

# AIGCNEWS

**发现值得关注的 AI 项目、论文和新进展，把好工具带进自己的工作。**

AIGCNEWS 将开源项目、学术论文、产品与行业动态整理成可搜索、可回看、可追踪的资料库。你可以在网站看榜单、找项目、挑 UI、读简报，也可以通过 **AIGC Radar MCP** 让 Agent 直接检索同一份数据。

![AIGCNEWS 当前首页：漫画风报头、多源榜单、日期回看、AI 热词与底部导航](docs/assets/readme/dashboard.png)

## 现在可以做什么

| 入口 | 能力 |
| --- | --- |
| [今日 AI 动态](https://aigcnews.cn/) | 切换 GitHub、论文、新闻、AI 产品、极客热议与推文动态；查看热度、项目 Star 增长，并通过日历回看历史榜单。侧栏提供 AI 热词解释、出处和历史新词。 |
| [项目库](https://aigcnews.cn/projects) | 按自然语言、分类、标签和语言找项目；比较 Star 总数、24 小时增长、近 14 天趋势与名次变化，查看项目详情、README 并收藏。 |
| [网页收藏](https://aigcnews.cn/projects?source=website) | 浏览工具网站，按分类检索；登录后可整理自己的项目与网页收藏。 |
| [UI 灵感库](https://aigcnews.cn/ui-library) | 浏览组件、整页模板、主题和图标；按用途、风格、框架筛选，预览效果，复制源码或交给 Agent 的整合提示词，并查看来源、依赖和许可。 |
| 论文阅读 | 从论文榜单进入站内阅读页，查看摘要、PDF 与原文；登录后可使用论文对话。 |
| [AI 简报](https://aigcnews.cn/report) | 按综合、学术、工程、行业、产品、社区等方向阅读，切换全文与导读；游客可看预览，登录后查看完整内容。 |
| [情报追踪](https://aigcnews.cn/subscriptions) | 关注关键词或某个项目的 Star 增长，自动汇总个人简报；按需投递到已验证的邮箱、Telegram、Discord 或 Webhook。 |
| [X 动态](https://aigcnews.cn/x) | 按厂商与模型生态选择关注账号，查看中文译文、图文和视频，浏览最近 24 小时或指定日期的动态；桌面端支持纯文字阅读与本机收藏。自托管时需要启用数据源并配置相应凭据。 |

网站提供中英文界面、明暗主题、手机布局与 PWA 安装。所有有效注册账号均可免费使用原会员功能，包括 10 条追踪规则和 UI 素材不限次复制；登录、Token 权限与调用额度仍然生效，不再提供新会员购买。

## 界面预览

以下截图摄于 2026 年 10 月，来自线上站点；条目、日期和统计会随采集更新。

| 项目库：榜单、详情与增长趋势 | UI 灵感库：效果预览与素材筛选 |
| --- | --- |
| ![项目库的分类侧栏、热榜、项目详情与 Star 增长曲线](docs/assets/readme/projects.png) | ![UI 灵感库中的整页模板、框架与用途筛选](docs/assets/readme/ui-library.png) |

| AI 简报：按方向阅读与导读 | MCP：复制提示词，浏览器授权 |
| --- | --- |
| ![AI 简报的内容摘要、技术亮点与工程动态，游客预览](docs/assets/readme/report.png) | ![新版 MCP 接入页的一键配置提示词与浏览器授权入口](docs/assets/readme/mcp.png) |

**X 动态：账号分组、中文译文与历史回看**

![X 动态的图文视频卡片、日期筛选与按厂商和模型生态分组的关注账号](docs/assets/readme/x-updates.png)

<details>
<summary>查看手机界面</summary>

<p align="center">
  <img src="docs/assets/readme/mobile-dashboard.png" alt="手机版首页：统计卡片、可横向切换的信息源、榜单与底部导航" width="390">
</p>

</details>

## 让 Agent 使用 AIGC Radar

### MCP 接入

1. 打开 [MCP 接入页](https://aigcnews.cn/mcp)，复制配置提示词。
2. 粘贴给你正在使用的 AI 编程 Agent，让它完成客户端配置。
3. 支持浏览器授权的客户端会打开授权页，登录并同意后即可使用账号能力。不支持的客户端可使用页面提供的安装提示词或手动配置。

| 连接方式 | Streamable HTTP 地址 |
| --- | --- |
| 浏览器授权 | `https://aigcnews.cn/api/mcp/oauth` |
| 公开工具 / 手动 Bearer Token | `https://aigcnews.cn/api/mcp` |

接好后可以直接问：

> 找适合做本地知识库的 RAG 项目，比较最近更新和 Star 增长。
>
> 找一个带动画的 React 首屏，读取原版源码、依赖与许可。
>
> 搜索关于 Agent 评测的论文，再看看本周相关榜单。

| 任务 | 主要工具 |
| --- | --- |
| 找 AI 项目或其他开源软件 | `search_github_ai_projects`、`search_github_projects` |
| 查看项目分类与 README | `get_project_categories`、`get_github_project_detail` |
| 查论文、索引内容与榜单 | `search_papers`、`get_paper_detail`、`search_documents`、`get_top_items` |
| 找 UI、读取源码与图标 | `search_ui_templates`、`get_ui_template`、`search_ui_icons`、`get_ui_icon` |
| 读取个人收藏与追踪 | `search_my_project_favorites`、`get_my_tracking` |
| 查看剩余额度与重置时间 | `get_my_quota` |

公开工具支持匿名调用；个人工具（含追踪读取）对所有有效账号免费开放，需要账号授权及相应 Token scope。MCP 与 `/api/v1` 共用调用额度：注册账号每 24 小时 200 次、滚动 30 天 4,000 次；详情见 [MCP 接入页](https://aigcnews.cn/mcp)，登录后也可用 `get_my_quota` 查询实际余额。完整工具参数、资源、提示词与鉴权说明见 [MCP 文档](docs/mcp-server.md)。

### dsh 原生插件

[dsh-aigc-radar](https://github.com/Kaixxrua/dsh-aigc-radar) 使用同一套 MCP 数据，在 dsh Web UI 中展示原生搜索卡片，并提供项目复用提示。

```sh
dsh plugin --profile web add dsh-aigc-radar
```

不配置 Token 也能使用公开工具。需要账号配额与个人能力时，打开 [DSH 接入页](https://aigcnews.cn/dsh) 完成配置。

## 本地开发与自托管

核心运行环境为 **Python 3.12、Node.js 22、Go 1.26 和 Docker Compose v2**；Go 版本以 [go.mod](mcp-go/go.mod) 为准，容器构建会准备对应工具链。

```bash
git clone https://github.com/Kaixxrua/AIGCNEWS.git
cd AIGCNEWS
cp .env.example .env
openssl rand -hex 32
```

将生成的随机值写入 `.env` 的 `JWT_SECRET_KEY`，再按需要配置模型服务、邮件、第三方登录和数据源。首次部署需要构建镜像、准备 TLS 证书并应用数据库迁移；`scripts/manage_main_stack.sh up` 启动的是已有镜像。

- [自托管指南](docs/self-hosting.zh-CN.md)：环境变量、依赖、证书、端口与本地开发。
- [核心 Compose](docker/docker-compose.yml)：后端、MCP、前端及存储服务的实际编排。
- [UI 素材库说明](docs/ui-library.md)：素材目录、源码、预览与来源许可的组织方式。

**源码与线上内容分开交付。** 线上数据库、账号凭据、完整 UI 库发布素材和私有部署配置不随 Git 仓库分发。干净检出的构建使用[最小 UI 目录夹具](scripts/ci/materialize_ui_catalog_fixture.py)；该夹具用于开发与 CI，不是线上素材库。自己的实例需要准备数据与素材，不能仅靠克隆仓库复现截图中的全部内容。

## 项目结构

| 目录 | 职责 |
| --- | --- |
| `frontend/` | Vue 3、TypeScript、Vite：网站、移动端布局、PDF 阅读、UI 预览与 PWA。 |
| `backend/` | FastAPI：账号、REST/SSE、采集调度、项目检索、论文处理、简报与追踪。 |
| `mcp-go/` | 独立 Go MCP 服务：协议入口、工具分派、鉴权、配额与 UI 源码读取。 |
| `docker/` | Docker Compose 编排；PostgreSQL 为主库，Redis、Milvus 与 Neo4j 提供缓存、向量和图谱能力。 |
| `scripts/` | 数据维护、素材处理、迁移、构建与交付工具。 |
| `docs/` | 使用说明、架构、运维与设计记录。 |

数据从采集、标准化与富化进入 PostgreSQL，再服务于网站、搜索、榜单、简报和 MCP。系统分层与模块细节见[架构文档](docs/architecture.md)。

## 文档与贡献

- [文档索引](docs/README.md)
- [MCP 协议与接入](docs/mcp-server.md)
- [个人情报追踪](docs/personal-tracking.md)
- [X 数据源配置](docs/x-source-runbook.md)
- [贡献指南](CONTRIBUTING.md) · [安全问题报告](SECURITY.md) · [行为准则](CODE_OF_CONDUCT.md)

## 许可与数据归属

代码与文档采用 [GNU AGPL-3.0](LICENSE)。项目名称、Logo、漫画插画、截图及宣传素材不属于开源许可范围；公开部署或分发 fork 时需使用自己的品牌，详见 [NOTICE](NOTICE)。

聚合的论文、项目元数据、新闻与社交内容归原作者和平台所有。UI 素材与图标分别遵守其来源许可，使用时保留相应署名、LICENSE 与 NOTICE。真实凭据、采集快照和生产数据库不在本仓库中。

## 社区致谢

AIGCNEWS 认可并感谢 [LINUX DO 社区](https://linux.do/) 为开发者提供开放的技术交流与知识分享空间。
