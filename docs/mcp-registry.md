# AIGC Radar MCP Registry 发布手册

本文描述如何把 AIGC Radar MCP 登记到公开 MCP registry 与目录站。元数据文件是仓库根目录的
[`server.json`](../server.json)。

## 元数据维护原则

- `name` / `title` / `description` / `version` 与生产一致性由 `backend/tests/test_mcp_registry_metadata.py`
  守护：`version` 必须等于生产环境 `initialize` 返回的 `serverInfo.version`（当前 `1.2.0`），
  `description` 不得超过官方 schema 的 100 字符上限。serverInfo 更名/升版的提交部署上线**之后**再
  publish，否则 registry 元数据与实际服务不一致。
- `title`（AIGC Radar MCP）是目录站展示名，`icons[0].src` 指向生产 PNG logo，
  `websiteUrl` 指向 Web 站点首页；改域名时三处与 `remotes[0].url` 一起改。
- `remotes[0].url` 指向生产公网 endpoint（当前 `https://aigcnews.cn/api/mcp`）。
  更换域名或路径时同步修改本文件并重新 publish。
- 命名空间 `io.github.kaixxrua` 绑定 GitHub 账号 Kaixxrua，publish 时用该账号完成 GitHub OAuth。
- 主仓库未公开前，`server.json` 不带 `repository`：registry 与目录站会把它显示成链接，指向私有仓库只会 404。
  仓库公开时再加回，并同步修改 `test_repository_omitted_while_main_repo_is_private`。
- 不得带着未替换的占位符或不可达 URL publish。

## 官方 MCP Registry（registry.modelcontextprotocol.io）

发布使用官方 `mcp-publisher` CLI（需要本机交互式 GitHub 授权，必须由维护者本人执行）：

```bash
# 1. 安装（参见官方仓库 modelcontextprotocol/registry 的安装说明）
brew install mcp-publisher        # 或 go install / 下载 release 二进制

# 2. GitHub 设备码授权（绑定 io.github.kaixxrua 命名空间）
mcp-publisher login github

# 3. 本地校验 server.json
mcp-publisher validate
```

注意：`server.json` 已于 2026-08-05 对照当时最新的官方 schema（2025-10-17 版）完成在线校验，
`description` ≤100 字符等硬约束由上述测试持续守护。若日后 `mcp-publisher validate` 提示有更新的
schema 版本，按其提示升级 `$schema` URL 并重跑测试。

```bash
# 4. 发布（在生产部署了对应 serverInfo 版本之后执行）
mcp-publisher publish
```

发布后可在官方 registry 查询 `io.github.kaixxrua/aigc-radar` 确认上线。

## 其他目录站

下表是 2026-10 核实的提交方式。各站规则常变，提交前以站点当时的页面为准。

| 目录 | 提交方式 | 填写要点 |
| --- | --- | --- |
| PulseMCP | 2026-09 起暂停人工提交；站方说明恢复后自动收录官方 registry | 无需操作，发布到官方 registry 即可 |
| mcp.directory | 从官方 registry 自动发现 | registry 发布后可认领条目，获得验证标记和编辑权 |
| Smithery（smithery.ai） | 登录后 smithery.ai/new，选 URL 方式；不要求仓库 | 填匿名入口 `https://aigcnews.cn/api/mcp`。用户经 Smithery 网关（`*.run.tools`）连接，匿名额度按网关出口 IP 计、被所有经它的用户共用。不填 OAuth 入口：Smithery 对上游走 CIMD，我们只支持 DCR |
| mcp.so | `/submit?type=remote-server`（Remote Server 页），只填 Name 和 Remote endpoint URL | 页面只给 $39 付费提交；首页 FAQ 另写可在 GitHub chatmcp/mcp-directory 提 issue |
| awesome-remote-mcp-servers（jaw9c） | 向 GitHub 仓库提 PR，在 README 表格加一行 | 接受 Open 鉴权和官网链接，不要求公开仓库；表格行见下 |
| awesome-mcp-servers（punkpeye） | 向 GitHub 仓库提 PR | 只收源码公开的服务器，主仓库公开前不提 |

### 提交素材

- 名称：AIGC Radar MCP（awesome 表格里写 AIGC Radar）
- 一句话描述（与 server.json 相同，≤100 字符）：AI-vertical index: arXiv papers, curated GitHub AI projects, daily rankings. Zero-setup, read-only.
- 入口：
  - 匿名 `https://aigcnews.cn/api/mcp`，也接受 /mcp 页创建的 Bearer 令牌；
  - OAuth `https://aigcnews.cn/api/mcp/oauth`：浏览器授权，DCR + PKCE S256。
- 官网 https://aigcnews.cn ，接入说明 https://aigcnews.cn/mcp ，图标 https://aigcnews.cn/logo.png
- awesome-remote-mcp-servers 表格行：

  ```text
  | AIGC Radar | Search | `https://aigcnews.cn/api/mcp` | Open / API Key | [AIGCNEWS](https://aigcnews.cn) |
  ```

## 变更与下线

- endpoint、工具面、鉴权语义变化：更新 server.json → 部署 → `mcp-publisher publish`。
- 下线服务：先从各目录移除条目，再关闭公网 endpoint。
