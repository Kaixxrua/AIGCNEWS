# MCP 引流待办清单

> 已完成：工具结果回链（`033a5a9`）、SEO 闭环（`1b5fa3d`）、分发素材（`90f7289`）、
> README 徽章与一键安装 deeplink（`f8a6062`）、论文阅读页游客只读开放（`525db63`，Red 变更已按流程验证）。
> 本文件只列**尚未做**的事项，完成一项勾掉一项，全部勾完即可归档删除。

## 1. 六家目录提交（手动，需本人账号）

素材（中英简介、标签、UTM 链接）全部在 [docs/mcp-distribution.md](mcp-distribution.md)，复制粘贴即可。按优先级：

- [ ] mcp.so —— https://mcp.so/submit （中文用户多，优先级最高）
- [ ] Smithery —— https://smithery.ai/new （仓库根 `smithery.yaml` 已就位，导入 GitHub 仓库即可）
- [ ] Glama —— https://glama.ai/mcp/servers （提交后认领条目补全描述）
- [ ] mcpservers.org —— https://mcpservers.org/submit
- [ ] PulseMCP —— https://www.pulsemcp.com/submit （curl 403 系 CF 反爬，用浏览器打开）
- [ ] awesome-mcp-servers —— 向 https://github.com/punkpeye/awesome-mcp-servers 提 PR（条目示例见分发文档）

## 2. README 展示面（registry 点击后的第一落点）✅ 已完成（`f8a6062`）

README 与 README.zh-CN 顶部已挂：在线站点徽章（链 `/mcp?utm_source=github&utm_medium=readme`）、
Cursor 官方 deeplink 徽章、VS Code 徽章（GitHub 会剥离 `vscode:` 协议 href，故链到 `/mcp` 落地页，
页内提供各客户端一键安装）。存档说明，无需再动。

## 3. `/papers/:id/read` 游客转化决策 ✅ 已完成（`525db63`）

采"游客只读预览"方案：路由放开（移除 `requiresAuth`），正文/PDF 游客可读，
对话与截图追问按登录态降级为顶部登录引导条（登录后回跳原页）。
Red 流程验证：路由契约测试锚定 meta 无鉴权标记、匿名不重定向；
控制器层守卫全部需鉴权的会话 API 调用。

## 4. 效果验证（提交完成后 1-2 周）

- [ ] 站点分析中按 `utm_source` 分组观察：各目录（`utm_medium=directory`）、MCP 工具结果（`utm_medium=tool`）、日报资源（`utm_medium=resource`）三路各自带来多少访问。
- [ ] 不支持自定义链接的目录改看 referer 维度。
- [ ] 复查各目录条目是否被编辑改坏描述，install 按钮能否正常 initialize。

## 5. 可选增强（低优先级，做了 1-4 再说）

- [x] 动态 sitemap：后端 `GET /api/sitemap.xml`（近 90 天 arXiv 论文阅读页，上限 5000 条，
  `Cache-Control: max-age=3600`），robots.txt 并列声明并显式 `Allow: /api/sitemap.xml`
  绕开 `/api/` 整段 Disallow。静态 7 路由 sitemap 保留不变。
- [ ] `/mcp` 及榜单页 prerender/SSR：SPA 无服务端渲染，爬虫只能读 meta，收录深度有限。
  （工程量大，需单独评估，不随引流批次做。）
- [ ] npm stdio 薄桥接包（独立小 repo，~100 行，包装远程 endpoint）：覆盖只要本地 stdio 的用户与偏好安装包的目录。**注意是新增制品，不是把 MCP 模块拆出主仓。**
  （阻塞：需新建 GitHub 仓库与 npm 账号，本人操作。）
