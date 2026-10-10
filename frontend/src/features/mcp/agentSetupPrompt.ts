import { DSH_PATCH_PATH, DSH_PLUGIN_INSTALL_METHODS, dshPatchLines } from './dshPlugin'
import { MCP_TOKEN_PLACEHOLDER, installCodeRedeemUrl } from './installCode'
import { manualMcpEndpoint } from './manualMcpConfig'
import { MCP_OAUTH_ENDPOINT } from './mcpOAuth'

/**
 * 「复制给 Agent 的配置提示词」：/mcp 与 /dsh 只留这一颗主按钮，选客户端、选终端、跑命令都交给用户自己的 Agent。
 *
 * 两版提示词都不带 Token：
 * - MCP 版：客户端连 MCP_OAUTH_ENDPOINT，被质询后打开本站授权页，由用户本人登录并点「同意」；游客也能复制，授权时再登录。
 *   登录了会附一枚一次性安装码，给不支持浏览器授权的客户端在本机换 Token（见 installCode.ts）；游客版让这类客户端停下，
 *   指回页面上的「手动配置」。
 * - dsh 版：插件只认配置里的 mcpToken，Agent 先写占位值，再用安装码换来账号的 DSH 专用 Token 原地替换。
 * 接好后让 Agent 调 get_my_quota 回报档位与额度（不计配额）。
 *
 * 提示词是给 Agent 读的整段文字，含命令、JSON 与 YAML，不进 vue-i18n 的消息表（{ } @ | 都要转义），按界面语言二选一。
 * 安装码只经安全剪贴板复制，页面预览用 COMMAND_TOKEN_SLOT 占位。
 */
const SERVER_NAME = 'aigc-news'
const QUOTA_TOOL = 'get_my_quota'

type PromptLocale = 'zh-CN' | 'en-US'

const promptLocale = (locale: string): PromptLocale => (locale.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en-US')

const url = MCP_OAUTH_ENDPOINT
const vscodeServer = JSON.stringify({ name: SERVER_NAME, type: 'http', url })

const originOf = (pageUrl: string) => {
  try {
    return new URL(pageUrl).origin
  } catch {
    return pageUrl.replace(/\/(mcp|dsh)\/?$/, '')
  }
}

/** POSIX shell：换来的 Token 只进变量，直接替换配置文件里的占位符，不出现在输出里。 */
const redeemCommand = (origin: string, code: string, clientName: string, configFile: string) =>
  `T="$(curl -fsS -X POST ${installCodeRedeemUrl(origin)} -H 'Content-Type: application/json' -H 'Accept: text/plain' ` +
  `-d '{"code":"${code}","client_name":"${clientName}"}')" && [ -n "$T" ] && ` +
  `perl -pi -e "s/${MCP_TOKEN_PLACEHOLDER}/$T/g" ${configFile}`

interface McpInstall {
  code: string
  bearerUrl: string
  redeem: (clientName: string, configFile: string) => string
}

const mcpPrompt: Record<PromptLocale, (manualPageUrl: string, install: McpInstall | null) => string[]> = {
  'zh-CN': (manualPageUrl, install) => [
    install
      ? '请帮我把 AIGC Radar MCP 接入你所在的这个 AI 客户端（我另有说明的除外）。它用浏览器授权；客户端不支持浏览器授权时，用第 4 步的一次性安装码换 Token。两种方式都不需要我复制 Token。'
      : '请帮我把 AIGC Radar MCP 接入你所在的这个 AI 客户端（我另有说明的除外）。它用浏览器授权，不需要 Token。',
    '',
    `服务名：${SERVER_NAME}`,
    `服务地址：${url}（Streamable HTTP）`,
    ...(install ? [`一次性安装码：${install.code}（只在第 4 步用；10 分钟内有效，只能兑换一次）`] : []),
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
    ...(install
      ? [
          '4. 这个客户端不支持浏览器授权（OAuth）的话，改用上面的一次性安装码：',
          `   a. 照客户端的格式加一个远程 HTTP MCP 服务器：服务名 ${SERVER_NAME}，地址 ${install.bearerUrl}，请求头 Authorization 先写成 Bearer ${MCP_TOKEN_PLACEHOLDER}。`,
          '   b. 运行下面这条命令，用安装码换 Token 并替换配置文件里的占位符（把 <配置文件> 换成上一步写的文件，<客户端名> 换成这个客户端的名字）。Token 不会出现在输出里，你也不要读取、打印或复述它：',
          `      ${install.redeem('<客户端名>', '<配置文件>')}`,
          '      Windows 上改用 PowerShell 的 Invoke-RestMethod 发同样的请求，再替换占位符。',
          `   c. 客户端只能在图形界面里配置，或者命令报错（安装码过期或已用过）时，停下，告诉我回 ${manualPageUrl} 重新复制提示词，或改用页面里的「手动配置」。`,
        ]
      : [`4. 这个客户端不支持浏览器授权（OAuth）的话就停下，告诉我改用 ${manualPageUrl} 页面里的「手动配置」。`]),
    '5. 要重启客户端或新开会话才生效的，直接告诉我。',
    install
      ? `6. 接好后（我授权完成，或者安装码兑换成功），调用 ${SERVER_NAME} 的 ${QUOTA_TOOL} 工具确认接通（它不消耗调用额度），把查到的档位和剩余额度告诉我。`
      : `6. 我授权后，调用 ${SERVER_NAME} 的 ${QUOTA_TOOL} 工具确认接通（它不消耗调用额度），把查到的档位和剩余额度告诉我。`,
  ],
  'en-US': (manualPageUrl, install) => [
    install
      ? 'Please connect AIGC Radar MCP to the AI client you are running in (unless I say otherwise). It uses browser authorization; if the client does not support that, step 4 trades a one-time install code for a token. Either way, I do not need to copy a token.'
      : 'Please connect AIGC Radar MCP to the AI client you are running in (unless I say otherwise). It uses browser authorization, so no token is needed.',
    '',
    `Server name: ${SERVER_NAME}`,
    `Server URL: ${url} (Streamable HTTP)`,
    ...(install ? [`One-time install code: ${install.code} (only for step 4; valid for 10 minutes, redeemable once)`] : []),
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
    ...(install
      ? [
          '4. If this client does not support browser (OAuth) authorization, use the install code above instead:',
          `   a. Add a remote HTTP MCP server in the client's own format: name ${SERVER_NAME}, URL ${install.bearerUrl}, with the Authorization header set to Bearer ${MCP_TOKEN_PLACEHOLDER} for now.`,
          '   b. Run this command to trade the install code for a token and replace the placeholder in the config file (put the file from step a in place of <config file>, and this client\'s name in place of <client name>). The token never appears in the output; do not read, print or repeat it:',
          `      ${install.redeem('<client name>', '<config file>')}`,
          '      On Windows, send the same request with PowerShell\'s Invoke-RestMethod, then replace the placeholder.',
          `   c. If the client can only be configured in its UI, or the command fails (the code expired or was already used), stop and tell me to copy a fresh prompt from ${manualPageUrl}, or to use Manual setup there.`,
        ]
      : [`4. If this client does not support browser (OAuth) authorization, stop and tell me to use Manual setup on ${manualPageUrl} instead.`]),
    '5. If the client needs a restart or a new session before the change takes effect, tell me.',
    install
      ? `6. Once connected (after I authorize, or after the install code is redeemed), call the ${SERVER_NAME} ${QUOTA_TOOL} tool to confirm the connection (it does not use any call quota) and tell me the plan and remaining quota it reports.`
      : `6. After I authorize, call the ${SERVER_NAME} ${QUOTA_TOOL} tool to confirm the connection (it does not use any call quota) and tell me the plan and remaining quota it reports.`,
  ],
}

/**
 * MCP 版提示词；manualPageUrl 是当前入口的 /mcp 页（备用入口打开时指回备用入口），Bearer 地址与兑换地址也跟它的 origin 走。
 * installCode 为空（游客、或暂时拿不到码）时不带安装码那一步。
 */
export function buildMcpAgentPrompt(locale: string, manualPageUrl: string, installCode?: string | null): string {
  const origin = originOf(manualPageUrl)
  const install: McpInstall | null = installCode
    ? {
        code: installCode,
        bearerUrl: manualMcpEndpoint(origin),
        redeem: (clientName, configFile) => redeemCommand(origin, installCode, clientName, configFile),
      }
    : null
  return mcpPrompt[promptLocale(locale)](manualPageUrl, install).join('\n')
}

const [npmInstall, githubInstall] = DSH_PLUGIN_INSTALL_METHODS.map((method) => method.command)
const FENCE = '```'

/**
 * 用安装码换 DSH Token 并替换补丁文件里的占位值：dsh 用户一定装了 Node（≥18 自带 fetch），一行脚本在 macOS、Linux、
 * Windows 上都能跑。脚本里不用双引号、$、反引号和 !，放进各家 shell 的双引号里都不会被改写；Token 只进文件，
 * 输出只有一句「写好了」或错误原因。
 */
const dshRedeemCommand = (origin: string, code: string) =>
  'node -e "' +
  "const fs=require('fs'),f=require('path').join(require('os').homedir(),'.dsh','profiles','web','cordis.patch.yml'),s=fs.readFileSync(f,'utf8');" +
  `if(s.indexOf('${MCP_TOKEN_PLACEHOLDER}')<0)throw new Error('placeholder not found in '+f);` +
  `fetch('${installCodeRedeemUrl(origin)}',{method:'POST',headers:{'content-type':'application/json',accept:'text/plain'},body:JSON.stringify({code:'${code}'})})` +
  ".then(async r=>{const t=(await r.text()).trim();if(r.status>=300||t.indexOf('aigc_mcp_')<0)throw new Error('install code rejected, HTTP '+r.status);" +
  `fs.writeFileSync(f,s.split('${MCP_TOKEN_PLACEHOLDER}').join(t));console.log('mcpToken written to '+f)})` +
  '.catch(e=>{console.error(e.message);process.exitCode=1})"'

const dshPrompt: Record<PromptLocale, (patch: string, redeem: string, dshPageUrl: string) => string[]> = {
  'zh-CN': (patch, redeem, dshPageUrl) => [
    '请帮我在 dsh 里装好 AIGC Radar 插件（dsh-aigc-radar），并用一次性安装码把我账号的专属 Token 配进 web profile。',
    '',
    `1. 安装插件：${npmInstall}`,
    `   npm 装不上（网络或镜像问题）时，改从 GitHub 装：${githubInstall}`,
    `2. 写配置。目标文件是 ${DSH_PATCH_PATH}，先读一下：`,
    '   - 文件不存在、是空的，或者只有注释和 []：整个文件写成下面这段；',
    '   - 已经有别的补丁：把这一项追加到列表末尾，原有内容原样保留；',
    '   - 已经有 id 为 aigc-radar 的项：只把它的 mcpToken 换成下面的占位值。',
    `${FENCE}yaml`,
    patch,
    FENCE,
    '3. 运行下面这条命令，用一次性安装码换取 Token，替换上面那个文件里的占位值。安装码 10 分钟内有效、只能兑换一次；Token 不会出现在输出里，你也不要读取、打印或复述它（也别用 --dump-config 查看配置）：',
    `   ${redeem}`,
    '   输出 mcpToken written 就是写好了；报错的话把错误告诉我，不要拿同一个安装码重试。',
    '4. 告诉我重启 dsh（npx @deepseek-ai/dsh web），再在 dsh 里问一句「有没有现成的 RAG 框架」试试。',
    '',
    `安装码过期或已用过时，请我回 ${dshPageUrl} 重新复制提示词。`,
  ],
  'en-US': (patch, redeem, dshPageUrl) => [
    'Please install the AIGC Radar plugin (dsh-aigc-radar) in dsh and use a one-time install code to add my personal token to its web profile.',
    '',
    `1. Install the plugin: ${npmInstall}`,
    `   If npm fails (network or registry mirror problems), install from GitHub instead: ${githubInstall}`,
    `2. Write the configuration. The target file is ${DSH_PATCH_PATH}; read it first:`,
    '   - If it does not exist, is empty, or only holds comments and []: replace the whole file with the block below.',
    '   - If it already has other patches: append this item to the end of the list and keep everything else as it is.',
    '   - If it already has an item with id aigc-radar: only change its mcpToken to the placeholder value below.',
    `${FENCE}yaml`,
    patch,
    FENCE,
    '3. Run this command to trade the one-time install code for the token and replace the placeholder in that file. The code is valid for 10 minutes and can be redeemed once; the token never appears in the output, and you should not read, print or repeat it (do not use --dump-config to look at the configuration either):',
    `   ${redeem}`,
    '   It prints mcpToken written when it is done. If it fails, tell me the error and do not retry the same code.',
    '4. Tell me to restart dsh (npx @deepseek-ai/dsh web), then ask it "is there a ready-made RAG framework?" to try it out.',
    '',
    `If the install code has expired or was already used, ask me to copy a fresh prompt from ${dshPageUrl}.`,
  ],
}

/**
 * dsh 版提示词，带一次性安装码；dshPageUrl 是当前入口的 /dsh 页，兑换地址跟它的 origin 走。
 * 只交给安全剪贴板，或用 COMMAND_TOKEN_SLOT 占位后做预览。
 */
export function buildDshAgentPrompt(locale: string, installCode: string, dshPageUrl: string): string {
  const patch = dshPatchLines(MCP_TOKEN_PLACEHOLDER).join('\n')
  const redeem = dshRedeemCommand(originOf(dshPageUrl), installCode)
  return dshPrompt[promptLocale(locale)](patch, redeem, dshPageUrl).join('\n')
}
