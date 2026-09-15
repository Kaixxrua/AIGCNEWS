# UI 素材质量、分类与配色

已于 2026-09-11 发布到两个生产节点并通过公网验证。CN：20260911T035607192991Z-6757414b18f4；JP：20260911T035705604814Z-6757414b18f4。目录 SHA-256：9af19fc77a37f0c1f0b8094c8129da6050b32f7c130dc52e0772b96f7d7754e8。

目录 3,493 项，新增 42 套 tweakcn 官方配色、3 个 shadcn/ui 完整页面和 1 个导航区块。默认首页展示 39 项经过视觉检查的精选；全部目录仍可浏览。可成功渲染不等于已通过视觉评审。

## 来源与证据

- tweakcn：a3b47b37cba97dd637de517aab52c45ec0f83456，Apache-2.0。仅内置主题，保留原始 presets/config/helper 字节；CSS 由配置机械导出。预览面板展示真实变量，使用本地字体回退，不分发字体文件。
- shadcn/ui：3ba91b1cc83e1bbe4ab35a422ff2a694849c5048，MIT。dashboard-01、login-01、login-03、sidebar-07 来自官方注册表及递归依赖。预览挂载、Tailwind 变量语法兼容和字体回退只在构建层处理；原 TSX/CSS 不改写，外部头像使用原版回退。
- 归档固定版本 LICENSE、README、HTTP 元数据、源码哈希、许可证截图，以及 110 个预览依赖的版本、完整许可文本和 npm integrity。缺少打包 LICENSE 的依赖，其包版本声明和另行固定的上游许可分别记录，不假称属于同一提交。
- Tailark 本批未导入：候选树没有完整 LICENSE，未以单独 package.json 声明替代核查。
- 精选附带源码版本、实际截图和预览文件哈希；构建时验证评审覆盖当前文件。每日新候选不能继承其他素材的精选资格。

## 浏览与 MCP

入口分为精选、组件动效、页面区块、完整页面、配色主题和全部素材；提供用途细分类、设计风格筛选，保留旧分类/排行榜链接。主题支持浅色/深色、CSS 高亮及源码/提示词复制。账号登录、每天共 5 次与 VIP 额度策略未修改。

search_ui_templates 增加可选 kind、细分类 category 和 css 框架；旧中英文检索结果保持兼容。get_ui_template 的大配置文件使用 next_offset/file_offset 分段，偏移按 Unicode 字符计数，拼接后校验完整 SHA-256。普通文件仍完整返回；单文件入库上限 256 KiB，全局 MCP 100,000 字符封装上限不变。大依赖许可通过 license_notice_files 提供全文 URL 与哈希。

每日自动发布仍走已核查的 HyperUI 适配器。主题及 shadcn 本批属于固定版本核查导入，没有宣称自动视觉评审全部每日候选。

## 验证

- 88 次真实渲染通过：42 套主题各浅/深色及 4 个页面/区块。首次开发服务重载导致的连接失败已补测通过。
- 前端素材、分类、高亮和 MCP 模型测试 38 项；追踪红点回归 21 项；类型检查和生产构建通过。
- Go 全套测试、go vet、最终目录/MCP 契约及 Linux 构建通过，包括全部源文件完整取回、大文件重组哈希、边界参数和旧协议兼容。
- 发布器 9 项单元测试通过。实际镜像 17,996 个文件与冻结清单逐项一致。
- 实际发布镜像的浏览器验收覆盖精选排序、4 列、滚动、主题明暗、CSS 高亮、授权链接、登录拦截、双语搜索、用途/风格筛选、旧排行榜和手机布局。
- 保留 tracking-unread-20260911 已上线的 14 个前端文件并核对哈希；后端和数据库不在本次变更范围。

UI_LIBRARY_ASSET_MANIFEST 支持将已核验素材直接流式归档，避免大量 Windows 临时文件写入；普通构建仍直接输出素材。

生产回执：E:/Projects/AIGCNEWS-local/local/updates/ui-quality-20260911T034922Z，查看 status.json、edges.json、public-browser-checks.json、mcp-runtime-check.json。发布前已保存镜像、目录、源码及双节点版本；失败按日志回退并检查并发变更。

没有提交或推送：dev_session check 报告已有 dirty/staged/untracked 状态；未绕过保护，也未暂存其他工作。
