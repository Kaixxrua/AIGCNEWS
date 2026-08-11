# MCP 引流待办清单

> 已完成：工具结果回链（`033a5a9`）、SEO 闭环（`1b5fa3d`）、分发素材（`90f7289`）。
> 本文件只列**尚未做**的事项，完成一项勾掉一项，全部勾完即可归档删除。

## 1. 六家目录提交（手动，需本人账号）

素材（中英简介、标签、UTM 链接）全部在 [docs/mcp-distribution.md](mcp-distribution.md)，复制粘贴即可。按优先级：

- [ ] mcp.so —— https://mcp.so/submit （中文用户多，优先级最高）
- [ ] Smithery —— https://smithery.ai/new （仓库根 `smithery.yaml` 已就位，导入 GitHub 仓库即可）
- [ ] Glama —— https://glama.ai/mcp/servers （提交后认领条目补全描述）
- [ ] mcpservers.org —— https://mcpservers.org/submit
- [ ] PulseMCP —— https://www.pulsemcp.com/submit （curl 403 系 CF 反爬，用浏览器打开）
- [ ] awesome-mcp-servers —— 向 https://github.com/punkpeye/awesome-mcp-servers 提 PR（条目示例见分发文档）

## 2. README 展示面（registry 点击后的第一落点）

在 README 顶部（标题下方）补两块内容：

**a) 在线站点徽章**（.shields.io 静态徽章，链到落地页）：

```markdown
[![在线使用](https://img.shields.io/badge/%E5%9C%A8%E7%BA%BF%E4%BD%BF%E7%94%A8-aigcnews.cn-blue)](https://aigcnews.cn/mcp?utm_source=github&utm_medium=readme)
```

**b) 一键安装 deeplink**（减少"看到→装上"的摩擦，以下参数已按本仓库 endpoint 生成）：

```markdown
[![Install in Cursor](https://cursor.com/deeplink/mcp-install-dark.svg)](https://cursor.com/en-US/install-mcp?name=aigc-radar&config=eyJ1cmwiOiJodHRwczovL2FpZ2NuZXdzLmNuL2FwaS9tY3AifQ==)

[在 VS Code 中安装](vscode:mcp/install?%7B%22name%22%3A%22aigc-radar%22%2C%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Faigcnews.cn%2Fapi%2Fmcp%22%7D)
```

注意：deeplink 格式以 Cursor / VS Code 当时文档为准，提交前在各自客户端实测一次。

## 3. `/papers/:id/read` 游客转化决策（Red 变更，需单独评估）

MCP 回链把论文详情页作为主要落点之一，但该路由当前 `meta: { requiresAuth: true }`，
游客点击会撞登录墙，转化流失。选项：

- [ ] 决策并执行：完全放开为公开路由；或做游客只读预览（正文可读、交互/历史功能仍要求登录）。

属权限面变更，需按 Red 流程单独验证（路由守卫、路由策略测试 `routePolicy.test.ts`、后端 `/api/papers/:id` 接口的鉴权现状）。

## 4. 效果验证（提交完成后 1-2 周）

- [ ] 站点分析中按 `utm_source` 分组观察：各目录（`utm_medium=directory`）、MCP 工具结果（`utm_medium=tool`）、日报资源（`utm_medium=resource`）三路各自带来多少访问。
- [ ] 不支持自定义链接的目录改看 referer 维度。
- [ ] 复查各目录条目是否被编辑改坏描述，install 按钮能否正常 initialize。

## 5. 可选增强（低优先级，做了 1-4 再说）

- [ ] 动态 sitemap：论文/日报等详情页级别纳入索引（现为 7 条静态路由；可在后端出 `/sitemap.xml` 或由 Caddy 转发）。
- [ ] `/mcp` 及榜单页 prerender/SSR：SPA 无服务端渲染，爬虫只能读 meta，收录深度有限。
- [ ] npm stdio 薄桥接包（独立小 repo，~100 行，包装远程 endpoint）：覆盖只要本地 stdio 的用户与偏好安装包的目录。**注意是新增制品，不是把 MCP 模块拆出主仓。**
