import i18n from '@/i18n'

/**
 * /mcp 接入页「浏览器授权（OAuth）」版的文案独立成文件，沿用 mcpConnection.ts 的注入方式：主 locale 表的 mcp 段
 * 由其他工作流维护，这里在命令台与向导初始化时经 mergeLocaleMessage 注入 mcpOAuthSetup.*。
 * 「复制配置命令」「复制给 Agent 的配置提示词」两颗按钮沿用 mcpAutoCommand.* 的名字，不另写一份。
 */

type McpOAuthSetupMessages = {
  mcpOAuthSetup: {
    title: string
    stepDescription: string
    useToken: string
    useOAuth: string
    encodedSlot: string
    agentPromptHint: string
    result: {
      'claude-code': string
      codex: string
    }
    hint: {
      'claude-code': string
      codex: string
      vscode: string
      cursor: string
      opencode: string
    }
    clients: {
      codex: string
      opencode: string
    }
    agentPrompt: string
  }
}

const enUS: McpOAuthSetupMessages = {
  mcpOAuthSetup: {
    title: 'Authorize in your browser, no token to copy',
    stepDescription: 'Step 2: run the command in your terminal. This site’s authorization page opens in your browser: sign in and click Allow. No token to copy.',
    useToken: 'Use a manual token instead',
    useOAuth: 'Use browser authorization instead',
    encodedSlot: 'encoded script',
    agentPromptHint: 'Paste the prompt into your coding Agent and it runs the command. When the authorization page opens in your browser, you sign in and click Allow yourself. The prompt contains no token.',
    result: {
      'claude-code': 'Writes the endpoint to Claude Code user-level MCP configuration, then opens your browser to authorize.',
      codex: 'Writes the endpoint to Codex user configuration and opens your browser to authorize. Codex keeps the token itself: no environment variable to set.',
    },
    hint: {
      'claude-code': 'When this site’s authorization page opens, sign in and click Allow. If no browser opens, or your Claude Code has no mcp login command yet, type /mcp in Claude Code, pick aigc-news and choose Authenticate.',
      codex: 'When this site’s authorization page opens, sign in and click Allow. If no browser opens, run codex mcp login aigc-news.',
      vscode: 'Then run MCP: List Servers in VS Code and start aigc-news. Accept the sign-in prompt, then click Allow in your browser.',
      cursor: 'Merge aigc-news from {path} into Cursor’s mcp.json, press the login button next to aigc-news in Cursor’s MCP settings, then click Allow in your browser.',
      opencode: 'Merge aigc-news from {path} into your OpenCode config, run opencode mcp auth aigc-news, then click Allow in your browser.',
    },
    clients: {
      codex: 'Registers into Codex user configuration; after you authorize in the browser, Codex keeps the token itself.',
      opencode: 'Generates a remote MCP import file; OpenCode starts the browser authorization.',
    },
    agentPrompt: 'Configure AIGC Radar MCP for me (browser authorization).\n\nTarget client: {client}\nConfiguration target: {target}\nServer URL: {endpoint}\nExecution shell: {shell}\n\nInspect the existing configuration first, then run the command below. If it only creates an import file, merge or import aigc-news into the target client without overwriting other MCP settings. This server uses browser authorization: when the client connects, this site’s authorization page opens and I sign in and click Allow myself. Do not sign in, click or bypass the authorization for me, and do not ask for or configure a token. If this environment cannot open a browser (for example, it has no interactive terminal), tell me which command to run in my own terminal. After I authorize, verify that aigc-news connects and lists its tools; diagnose and fix any other errors.\n\nSetup command:\n```sh\n{command}\n```',
  },
}

const zhCN: McpOAuthSetupMessages = {
  mcpOAuthSetup: {
    title: '浏览器授权，不用复制 Token',
    stepDescription: '第 2 步：复制命令到终端运行，浏览器会打开本站授权页，登录后点「同意」即可，不用复制 Token。',
    useToken: '改用手动 Token',
    useOAuth: '改用浏览器授权',
    encodedSlot: '编码脚本',
    agentPromptHint: '把提示词粘贴给你的编码 Agent，它会运行命令；浏览器打开授权页后，由你本人登录并点「同意」。提示词里没有 Token。',
    result: {
      'claude-code': '执行后写入 Claude Code 用户级 MCP 配置，接着打开浏览器授权。',
      codex: '执行后写入 Codex 用户配置，并打开浏览器授权；Token 由 Codex 自己保存，不用设环境变量。',
    },
    hint: {
      'claude-code': '浏览器打开本站授权页后，登录并点「同意」。没弹出浏览器，或 Claude Code 版本较旧、没有 mcp login 命令时，在 Claude Code 里输入 /mcp，选 aigc-news，再选 Authenticate。',
      codex: '浏览器打开本站授权页后，登录并点「同意」。没弹出浏览器时，运行 codex mcp login aigc-news。',
      vscode: '注册后在 VS Code 里运行「MCP: List Servers」，启动 aigc-news；弹出登录提示时选允许，再在浏览器里点「同意」。',
      cursor: '把 {path} 里的 aigc-news 合并进 Cursor 的 mcp.json，在 Cursor 设置的 MCP 列表里点 aigc-news 旁的登录按钮，再在浏览器里点「同意」。',
      opencode: '把 {path} 里的 aigc-news 合并进 OpenCode 配置，运行 opencode mcp auth aigc-news，再在浏览器里点「同意」。',
    },
    clients: {
      codex: '注册到 Codex 用户配置；浏览器授权后，Token 由 Codex 自己保存。',
      opencode: '生成 remote MCP 导入文件，由 OpenCode 发起浏览器授权。',
    },
    agentPrompt: '请帮我配置 AIGC Radar MCP（浏览器授权版）。\n\n目标客户端：{client}\n配置目标：{target}\n服务地址：{endpoint}\n执行环境：{shell}\n\n请先检查现有配置，再执行下面的配置命令。若命令只生成导入文件，请在不覆盖其他 MCP 配置的前提下，将 aigc-news 合并或导入目标客户端。这个服务用浏览器授权：客户端连接时会打开本站授权页，由我本人登录并点「同意」。请不要替我登录、点击或绕过授权，也不要另外索要或配置 Token；如果当前环境打不开浏览器（例如没有交互式终端），请告诉我该在自己的终端里运行哪条命令。我授权后，验证 aigc-news 可以连接并列出工具；遇到其他错误请直接排查并修复。\n\n配置命令：\n```sh\n{command}\n```',
  },
}

/** 只给自带文案表的组件测试用：把这段并进测试自己的 i18n。 */
export const mcpOAuthSetupMessages = { 'en-US': enUS, 'zh-CN': zhCN } as const

let installed = false

export function installMcpOAuthSetupMessages(): void {
  if (installed) return
  installed = true
  i18n.global.mergeLocaleMessage('en-US', enUS)
  i18n.global.mergeLocaleMessage('zh-CN', zhCN)
}
