import { DSH_PATCH_PATH, DSH_PLUGIN_INSTALL_METHODS, dshPatchLines } from './dshPlugin'
import { MCP_OAUTH_ENDPOINT } from './mcpOAuth'

/**
 * 「复制给 Agent 的配置提示词」：/mcp 与 /dsh 只留这一颗主按钮，选客户端、选终端、跑命令都交给用户自己的 Agent。
 *
 * - MCP 版不带 Token：客户端连 MCP_OAUTH_ENDPOINT，被质询后打开本站授权页，由用户本人登录并点「同意」；
 *   游客也能复制，授权时再登录。不支持浏览器授权的客户端，提示词让 Agent 停下，指回页面上的「手动配置」。
 * - dsh 版带账号的 DSH 专用 Token（插件只认配置里的 mcpToken），只经安全剪贴板复制，页面上不出现明文。
 *
 * 提示词是给 Agent 读的整段文字，含命令、JSON 与 YAML，不进 vue-i18n 的消息表（{ } @ | 都要转义），按界面语言二选一。
 */
const SERVER_NAME = 'aigc-news'

type PromptLocale = 'zh-CN' | 'en-US'

const promptLocale = (locale: string): PromptLocale => (locale.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en-US')

const url = MCP_OAUTH_ENDPOINT
const vscodeServer = JSON.stringify({ name: SERVER_NAME, type: 'http', url })

const mcpPrompt: Record<PromptLocale, (manualPageUrl: string) => string[]> = {
  'zh-CN': (manualPageUrl) => [
    `请帮我把 AIGC Radar MCP 接入你所在的这个 AI 客户端（我另有说明的除外）。它用浏览器授权，不需要 Token。`,
    '',
    `服务名：${SERVER_NAME}`,
    `服务地址：${url}（Streamable HTTP）`,
    '',
    `1. 先确认你在哪个客户端里运行，看一下它现有的 MCP 配置。已有 ${SERVER_NAME} 就先删掉再加；别的 MCP 服务器一个都不要动。`,
    '2. 按客户端添加：',
    `   - Claude Code：运行 claude mcp add --scope user --transport http ${SERVER_NAME} ${url}，再运行 claude mcp login ${SERVER_NAME}；没有 login 命令的旧版本，请我在 Claude Code 里输入 /mcp，选 ${SERVER_NAME}，再选 Authenticate。`,
    `   - Codex：运行 codex mcp add ${SERVER_NAME} --url ${url}，它会自己打开浏览器；没打开就运行 codex mcp login ${SERVER_NAME}。`,
    `   - Cursor：在 ~/.cursor/mcp.json 的 mcpServers 里加上 "${SERVER_NAME}": { "url": "${url}" }，再请我在 Cursor 设置的 MCP 列表里点 ${SERVER_NAME} 旁的登录按钮。`,
    `   - VS Code：运行 code --add-mcp '${vscodeServer}'，再请我运行「MCP: List Servers」，启动 ${SERVER_NAME}。`,
    `   - OpenCode：在 ~/.config/opencode/opencode.json 的 mcp 里加上 "${SERVER_NAME}": { "type": "remote", "url": "${url}", "enabled": true }，再运行 opencode mcp auth ${SERVER_NAME}。`,
    '   - 其他客户端：照它的文档加一个远程 HTTP（Streamable HTTP）MCP 服务器，地址同上。',
    '3. 授权时浏览器会打开 AIGC Radar 的授权页，由我本人登录并点「同意」。不要替我登录、点击或绕过授权，也不要向我要 Token。当前环境打不开浏览器、或者你不能在我的电脑上执行命令时，告诉我该在自己的终端里运行哪条命令。',
    `4. 这个客户端不支持浏览器授权（OAuth）的话就停下，告诉我改用 ${manualPageUrl} 页面里的「手动配置」。`,
    '5. 要重启客户端或新开会话才生效的，直接告诉我。',
    `6. 我授权后，列出 ${SERVER_NAME} 的工具确认接通（列工具不消耗调用额度），再把结果告诉我。`,
  ],
  'en-US': (manualPageUrl) => [
    'Please connect AIGC Radar MCP to the AI client you are running in (unless I say otherwise). It uses browser authorization, so no token is needed.',
    '',
    `Server name: ${SERVER_NAME}`,
    `Server URL: ${url} (Streamable HTTP)`,
    '',
    `1. Work out which client you are running in and look at its MCP configuration. If ${SERVER_NAME} is already there, remove it before adding it again. Do not touch any other MCP server.`,
    '2. Add it for your client:',
    `   - Claude Code: run claude mcp add --scope user --transport http ${SERVER_NAME} ${url}, then claude mcp login ${SERVER_NAME}. On older versions without the login command, ask me to type /mcp in Claude Code, pick ${SERVER_NAME} and choose Authenticate.`,
    `   - Codex: run codex mcp add ${SERVER_NAME} --url ${url}. It opens the browser itself; if it does not, run codex mcp login ${SERVER_NAME}.`,
    `   - Cursor: add "${SERVER_NAME}": { "url": "${url}" } under mcpServers in ~/.cursor/mcp.json, then ask me to press the login button next to ${SERVER_NAME} in Cursor's MCP settings.`,
    `   - VS Code: run code --add-mcp '${vscodeServer}', then ask me to run "MCP: List Servers" and start ${SERVER_NAME}.`,
    `   - OpenCode: add "${SERVER_NAME}": { "type": "remote", "url": "${url}", "enabled": true } under mcp in ~/.config/opencode/opencode.json, then run opencode mcp auth ${SERVER_NAME}.`,
    '   - Any other client: add a remote HTTP (Streamable HTTP) MCP server with the same URL, following its documentation.',
    '3. Authorization opens the AIGC Radar authorization page in a browser, where I sign in and click Allow myself. Do not sign in, click or bypass authorization for me, and do not ask me for a token. If this environment cannot open a browser, or you cannot run commands on my computer, tell me which command to run in my own terminal.',
    `4. If this client does not support browser (OAuth) authorization, stop and tell me to use Manual setup on ${manualPageUrl} instead.`,
    '5. If the client needs a restart or a new session before the change takes effect, tell me.',
    `6. After I authorize, list the ${SERVER_NAME} tools to confirm the connection (listing tools does not use any call quota) and tell me the result.`,
  ],
}

/** MCP 版提示词；manualPageUrl 是当前入口的 /mcp 页（备用入口打开时指回备用入口）。 */
export function buildMcpAgentPrompt(locale: string, manualPageUrl: string): string {
  return mcpPrompt[promptLocale(locale)](manualPageUrl).join('\n')
}

const [npmInstall, githubInstall] = DSH_PLUGIN_INSTALL_METHODS.map((method) => method.command)
const FENCE = '```'

const dshPrompt: Record<PromptLocale, (patch: string) => string[]> = {
  'zh-CN': (patch) => [
    '请帮我在 dsh 里装好 AIGC Radar 插件（dsh-aigc-radar），并把我的专属 Token 配进 web profile。',
    '',
    `1. 安装插件：${npmInstall}`,
    `   npm 装不上（网络或镜像问题）时，改从 GitHub 装：${githubInstall}`,
    `2. 写配置。目标文件是 ${DSH_PATCH_PATH}，先读一下：`,
    '   - 文件不存在、是空的，或者只有注释和 []：整个文件写成下面这段；',
    '   - 已经有别的补丁：把这一项追加到列表末尾，原有内容原样保留；',
    '   - 已经有 id 为 aigc-radar 的项：只把它的 mcpToken 换成下面的值。',
    `${FENCE}yaml`,
    patch,
    FENCE,
    '3. 运行 dsh --profile web --dump-config，确认能看到 aigc-radar 的 mcpToken（不要把值贴出来）。',
    '4. 告诉我重启 dsh（npx @deepseek-ai/dsh web），再在 dsh 里问一句「有没有现成的 RAG 框架」试试。',
    '',
    '这段提示词里有我的专属 Token：不要在回复、日志或代码提交里复述它，也不要写进任何项目仓库。',
  ],
  'en-US': (patch) => [
    'Please install the AIGC Radar plugin (dsh-aigc-radar) in dsh and add my personal token to its web profile.',
    '',
    `1. Install the plugin: ${npmInstall}`,
    `   If npm fails (network or registry mirror problems), install from GitHub instead: ${githubInstall}`,
    `2. Write the configuration. The target file is ${DSH_PATCH_PATH}; read it first:`,
    '   - If it does not exist, is empty, or only holds comments and []: replace the whole file with the block below.',
    '   - If it already has other patches: append this item to the end of the list and keep everything else as it is.',
    '   - If it already has an item with id aigc-radar: only change its mcpToken to the value below.',
    `${FENCE}yaml`,
    patch,
    FENCE,
    '3. Run dsh --profile web --dump-config and check that aigc-radar has an mcpToken (do not paste the value).',
    '4. Tell me to restart dsh (npx @deepseek-ai/dsh web), then ask it "is there a ready-made RAG framework?" to try it out.',
    '',
    'This prompt contains my personal token: do not repeat it in replies, logs or commits, and do not write it into any project repository.',
  ],
}

/** dsh 版提示词，带账号的 DSH 专用 Token；只交给安全剪贴板，或用 COMMAND_TOKEN_SLOT 占位后做预览。 */
export function buildDshAgentPrompt(locale: string, token: string): string {
  return dshPrompt[promptLocale(locale)](dshPatchLines(token).join('\n')).join('\n')
}
