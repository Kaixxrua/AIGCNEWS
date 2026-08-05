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

均为 Web 表单提交，无需仓库内元数据（或仅参考 server.json 内容填写）：

| 目录 | 提交方式 | 填写要点 |
| --- | --- | --- |
| Smithery（smithery.ai） | 站点内 "Add Server" 表单 | Remote URL `https://aigcnews.cn/api/mcp`，transport 选 Streamable HTTP |
| mcp.so | 站点提交表单 | 名称 AIGC Radar MCP，描述可复用 server.json 的 description |
| awesome-mcp-servers | 向对应 GitHub 仓库提 PR | 归入 Data / Search 分类，链接本仓库 |

## 变更与下线

- endpoint、工具面、鉴权语义变化：更新 server.json → 部署 → `mcp-publisher publish`。
- 下线服务：先从各目录移除条目，再关闭公网 endpoint。
