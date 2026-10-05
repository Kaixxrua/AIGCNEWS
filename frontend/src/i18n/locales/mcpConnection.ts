import i18n from '@/i18n'

/**
 * 接入命令旁「等待连接 → 已连接」状态条的文案独立成文件，沿用 mcpUsage.ts 的注入方式：
 * 主 locale 表的 mcp/dsh 段各是一整行，由其他工作流维护，这里在状态条初始化时经 mergeLocaleMessage 注入 mcpConnection.*。
 * 「验证连接」「重新生成 Token」两处按钮名用参数传进来，跟着主表走，不另写一份。
 */

type McpConnectionMessages = {
  mcpConnection: {
    waitingTitle: string
    waitingBody: string
    waitingBodyDsh: string
    connectedTitle: string
    connectedBody: string
    seenTitle: string
    seenBody: string
    pausedTitle: string
    pausedBody: string
    goneTitle: string
    goneBody: string
    goneBodyDsh: string
    checkAgain: string
    checking: string
    tipsToggle: string
    justNow: string
    tips: {
      shell: string
      restart: string
      latest: string
      network: string
      dshConfig: string
      dshRestart: string
      dshAsk: string
      dshRotated: string
    }
  }
}

const enUS: McpConnectionMessages = {
  mcpConnection: {
    waitingTitle: 'Waiting for {client} to connect…',
    waitingBody: 'Run the command and restart {client}. This turns to Connected the moment it reaches AIGC Radar.',
    waitingBodyDsh: 'Run the command, restart dsh and ask it about an AI project. This turns to Connected on the plugin’s first search.',
    connectedTitle: 'Connected',
    connectedBody: '{client} reached AIGC Radar with this token at {time}.',
    seenTitle: 'Connected before',
    seenBody: 'This token was last used {time}. Reinstall it on another machine and this updates.',
    pausedTitle: 'No connection yet',
    pausedBody: 'Stopped checking on its own. Press Check again once it is set up.',
    goneTitle: 'This token no longer works',
    goneBody: 'It was deleted or replaced. Generate a new command.',
    goneBodyDsh: 'The token was regenerated or deleted elsewhere. Reload the page for a fresh command.',
    checkAgain: 'Check again',
    checking: 'Checking…',
    tipsToggle: 'Can’t connect?',
    justNow: 'just now',
    tips: {
      shell: 'Make sure the command ran to the end, without errors, in the terminal you picked (PowerShell, Command Prompt or Bash).',
      restart: 'Restart the client or open a new session: most clients read their MCP settings only at startup.',
      latest: 'Every Generate makes a new token and only the newest one is watched here, so run the command you copied last.',
      network: 'A company network or proxy may block aigcnews.cn. Use step 3, {verify}, to test the public handshake.',
      dshConfig: 'Run dsh --profile web --dump-config and check that the dsh-aigc-radar layer is there with a non-empty mcpToken.',
      dshRestart: "Restart dsh (npx {'@'}deepseek-ai/dsh web) after the command: a running dsh does not reload its config.",
      dshAsk: 'The plugin connects on its first search. Ask dsh something like “is there a ready-made RAG framework?”',
      dshRotated: 'Pressed {rotate}? The old token stopped working at once, so run the new command.',
    },
  },
}

const zhCN: McpConnectionMessages = {
  mcpConnection: {
    waitingTitle: '等待 {client} 连接…',
    waitingBody: '运行命令并重启 {client}，它一连上 AIGC Radar，这里就会变成「已连接」。',
    waitingBodyDsh: '运行命令、重启 dsh，再问它一个 AI 项目相关的问题；插件第一次搜索时，这里就会变成「已连接」。',
    connectedTitle: '已连接',
    connectedBody: '{client} 在 {time} 用这枚 Token 连上了 AIGC Radar。',
    seenTitle: '以前连上过',
    seenBody: '这枚 Token 最近一次使用是{time}。换台电脑重新安装后，这里会刷新。',
    pausedTitle: '还没检测到连接',
    pausedBody: '已停止自动检测，装好后点「再检查」。',
    goneTitle: '这枚 Token 已失效',
    goneBody: '它已被删除或替换，请重新生成配置命令。',
    goneBodyDsh: 'Token 已在别处重新生成或删除，刷新页面获取新命令。',
    checkAgain: '再检查',
    checking: '检查中…',
    tipsToggle: '连不上？',
    justNow: '刚刚',
    tips: {
      shell: '确认命令在你选的终端（PowerShell、命令提示符或 Bash）里完整运行、没有报错。',
      restart: '重启客户端或新开一个会话：多数客户端只在启动时读取 MCP 配置。',
      latest: '每次「生成」都是一枚新 Token，这里只认最新那一枚：请运行最后复制的那条命令。',
      network: '公司网络或代理可能拦着 aigcnews.cn：用第 3 步「{verify}」测一下公开握手。',
      dshConfig: '运行 dsh --profile web --dump-config，确认有 dsh-aigc-radar 配置层、mcpToken 不为空。',
      dshRestart: "运行命令后要重启 dsh（npx {'@'}deepseek-ai/dsh web），正在运行的 dsh 不会重新读取配置。",
      dshAsk: '插件在第一次搜索时才连接：在 dsh 里问一句「有没有现成的 RAG 框架」试试。',
      dshRotated: '点过「{rotate}」？旧 Token 立即失效，要重新运行新命令。',
    },
  },
}

/** 只给自带精简文案表的组件测试用：把这段并进测试自己的 i18n。 */
export const mcpConnectionMessages = { 'en-US': enUS, 'zh-CN': zhCN } as const

let installed = false

export function installMcpConnectionMessages(): void {
  if (installed) return
  installed = true
  i18n.global.mergeLocaleMessage('en-US', enUS)
  i18n.global.mergeLocaleMessage('zh-CN', zhCN)
}
