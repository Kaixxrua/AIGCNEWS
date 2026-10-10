# 前端依赖审计记录

2026-10-10 复核：生产依赖 `npm audit --omit=dev` 为 0 条告警；完整依赖树由 15 条降至 6 条，剩余告警均来自同一个上游问题。完整审计仍返回非零状态，不能据此声称所有依赖漏洞已清零。

## 已更新的开发依赖

- Vite 7.3.7、Vitest 4.1.11（含 mocker）、esbuild 0.28.2、UUID 11.1.1。
- 间接依赖 brace-expansion 2.1.7 / 5.0.12、fast-uri 3.1.8、undici 7.30.0。
- `postcss-selector-parser` 统一覆盖到 7.1.6，修复长选择器的二次复杂度问题；Tailwind 3 的默认范围仍会安装受影响的 6.x。覆盖后的生产构建通过，生成的 32 个 CSS 文件内容哈希与升级前一致。参见[上游公告](https://github.com/advisories/GHSA-rj75-hqrm-r3gf)。

## 尚无上游补丁的 braces 告警

[GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) 涉及深度嵌套的文件匹配表达式导致栈溢出。目前 `braces` 最新版本 3.0.3 仍在受影响范围内，公告未列出修复版本；[维护者讨论](https://github.com/micromatch/braces/issues/70) 对调用方接受不可信表达式的责任边界存在争议。

本项目依赖链为 `tailwindcss` / `@vue/eslint-config-typescript` → `chokidar` / `fast-glob` / `micromatch` → `braces`。npm 将这条链中的 6 个包分别计为高危，并非 6 个独立漏洞。

已核对的使用边界：

- 这些包均为开发依赖，不属于生产运行依赖。
- Tailwind 的文件匹配表达式来自 `frontend/tailwind.config.js` 中的固定 `content` 配置。
- Vue ESLint 配置使用固定的 `**/*.vue` 和本地忽略规则查找源码。
- UI 预览生成将组件源码作为 Tailwind 的 `raw` 内容输入，没有把该内容作为文件匹配表达式。
- 当前调用链没有发现接收网站用户输入作为 glob 表达式的入口。该结论仅覆盖现有调用方式，不代表依赖本身已经修复。

保留原包名、版本及审计告警，不通过改名、忽略告警或强制跨主版本升级消除审计数字。上游发布修复后，应更新锁文件并重新运行下列检查；使用与 CI 相同的 npm 版本验证干净安装，避免锁文件处理差异。任何新增的动态匹配表达式入口都需要重新评估。

```bash
cd frontend
npm ci
npm audit --omit=dev
npm audit
npm run typecheck
npm run lint
npm run test:unit -- --maxWorkers=2
npm run build
```
