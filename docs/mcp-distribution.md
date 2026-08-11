# AIGC Radar MCP 第三方目录分发清单

> 目的：把官方 registry 之外的 MCP 目录一次性铺开，给 aigcnews.cn 引流。
> 收录后引流效果通过 UTM 观察（`utm_source=<目录名>`）。

## 现状

- 官方 registry：`io.github.kaixxrua/aigc-radar`（server.json 已注册，`websiteUrl` 指向主站）。
- 竞品面（2026-08 对 mcp.so 全量 18,455 个 server 的扫描结论）：**无同定位竞品**。
  最近邻均不构成同位竞争：
  - `agentic-news`——通用新闻情报 agent，无论文/项目库/榜单体系；
  - `mcp_newsnow` / `newsnow-mcp-server` / `mcp-quanmiao-hotnews`——通用中文热榜，AI 只是其中一个版块；
  - `huggingface-daily-paper-mcp`、`arxiv-mcp-server` 系（~12 个）、`mcp-github-trending`、`producthunt-mcp-server`、`hn-trending-mcp`——全部是单源接口包装。
  - 注意 `mcp-server-aigc-hackers` 占用 "AIGC" 名字但实为图像/视频生成工具，描述里要把差异化写清楚避免混淆。

## 统一提交素材

| 字段 | 值 |
| --- | --- |
| Name | AIGC Radar |
| Endpoint | `https://aigcnews.cn/api/mcp`（streamable-http，零安装） |
| Website | `https://aigcnews.cn/mcp?utm_source=<目录名>&utm_medium=directory`（落地页，内置 9 客户端一键导入） |
| Icon | `https://aigcnews.cn/logo.png` |
| Repo | `https://github.com/Kaixxrua/AIGC_NEWS` |
| Tags | ai-news, arxiv, github-trending, producthunt, hackernews, daily-briefing, rankings, llm, agent, rag |

**Short description（EN，<140 字符）**

> AI-vertical radar: arXiv papers, curated GitHub AI projects (500+ stars), daily/weekly/monthly rankings, daily briefing. Zero-setup remote MCP.

**中文简介**

> AIGC Radar：AI 垂直雷达——arXiv 论文、精选 GitHub AI 项目库（≥500 star）、日/周/月榜单与每日日报。远程 MCP，零安装直连。

**Long description（EN，用于详情页）**

> AIGC Radar aggregates the AI industry's daily signals into one MCP endpoint: arXiv papers, a curated library of GitHub AI projects (500+ stars, categorized), Product Hunt / Hacker News / X / news cross-source rankings with official daily, weekly and monthly boards, plus a generated daily briefing. No API key, no install — point any streamable-HTTP MCP client at the endpoint. The companion site aigcnews.cn hosts the full rankings, project library and one-click client imports.

## 提交清单（按优先级）

1. **mcp.so** — https://mcp.so/submit （2026-08 核实可达）。中文用户占比高，与受众重合度最大，优先提交。
2. **Smithery** — https://smithery.ai/new （已核实）。仓库根已备 `smithery.yaml`（remote http 类型），导入 GitHub 仓库即可识别。
3. **Glama** — https://glama.ai/mcp/servers （已核实）。Glama 会定期扫 GitHub，提交后认领条目并补全描述。
4. **mcpservers.org** — https://mcpservers.org/submit （已核实）。
5. **PulseMCP** — https://www.pulsemcp.com/submit （curl 403 为 CF 反爬，用浏览器提交）。
6. **awesome-mcp-servers** — https://github.com/punkpeye/awesome-mcp-servers 提 PR。条目示例（图例以该 README 当时版本为准，🐍=Python ☁️=Cloud）：

   ```markdown
   - [Kaixxrua/AIGC_NEWS](https://github.com/Kaixxrua/AIGC_NEWS) 🐍 ☁️ - AI-vertical radar: arXiv papers, curated GitHub AI projects (500+ stars), daily/weekly/monthly cross-source rankings and daily briefing over streamable HTTP.
   ```

## 提交后验证

- 各目录条目页的 Install/Connect 按钮指向 `https://aigcnews.cn/api/mcp` 且能正常 initialize。
- 站点分析中观察 `utm_source` 为各目录名的访问量；若某目录不支持自定义链接，退而求其次看 referer。
- 收录 1-2 周后复查一次排名/展示是否生效，描述被编辑改坏时及时回改。

## 注意事项

- 描述一律保持事实性，不堆营销词——官方 registry 与多数目录有人工/自动审核。
- 各目录提交入口可能改版，链接失效时从站点首页找 "Submit" / "Add server" 入口。
- 引流主链路（MCP 工具结果内的 detail_url 与 attribution）已在后端落地，目录分发是放大器；两者 UTM 互相独立（`utm_medium=tool|resource|directory`）。
