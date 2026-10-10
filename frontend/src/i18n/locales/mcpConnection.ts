import i18n from '@/i18n'

/**
 * 「等待连接 → 已连接」状态条的文案独立成文件，沿用 mcpUsage.ts 的注入方式：
 * 主 locale 表的 mcp/dsh 段各是一整行，由其他工作流维护，这里在状态条初始化时经 mergeLocaleMessage 注入 mcpConnection.*。
 * agent.* 是「复制给 Agent」之后的回显，manual.* 是 /mcp 手动配置的；不分组的几条 dsh 与手动配置共用。
 * 「重新生成 Token」按钮名用参数传进来，跟着主表走，不另写一份。
 */

type McpConnectionMessages = {
  mcpConnection: {
    agent: {
      waitingTitle: string
      waitingBody: string
      authorizedTitle: string
      authorizedTitleUnnamed: string
      authorizedBody: string
      connectedTitle: string
      connectedBody: string
      connectedBodyUnnamed: string
      pausedTitle: string
      pausedBody: string
    }
    manual: {
      waitingTitle: string
      waitingBody: string
      connectedBody: string
    }
    waitingTitle: string
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
      agentBrowser: string
      agentAccount: string
      agentNetwork: string
      manualConfig: string
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
    agent: {
      waitingTitle: 'Waiting for your Agent to finish…',
      waitingBody: 'Paste the prompt into your Agent. Once it has set things up, your browser opens this site’s authorization page: click Allow and this turns to Connected.',
      authorizedTitle: '{client} is authorized, waiting for it to connect…',
      authorizedTitleUnnamed: 'Authorized, waiting for your client to connect…',
      authorizedBody: 'Authorization is done. This turns to Connected the first time your client calls AIGC Radar; some clients only connect after a restart or in a new session.',
      connectedTitle: 'Connected',
      connectedBody: '{client} reached AIGC Radar at {time}.',
      connectedBodyUnnamed: 'Your client reached AIGC Radar at {time}.',
      pausedTitle: 'Not connected yet',
      pausedBody: 'Stopped checking on its own. Press Check again once you have authorized.',
    },
    manual: {
      waitingTitle: 'Waiting for your client to connect…',
      waitingBody: 'Add the configuration to your client and restart it. This turns to Connected the moment it reaches AIGC Radar.',
      connectedBody: 'Your client reached AIGC Radar with this token at {time}.',
    },
    waitingTitle: 'Waiting for {client} to connect…',
    waitingBodyDsh: 'Once the Agent has installed it, restart dsh and ask it about an AI project. This turns to Connected on the plugin’s first search.',
    connectedTitle: 'Connected',
    connectedBody: '{client} reached AIGC Radar with this token at {time}.',
    seenTitle: 'Connected before',
    seenBody: 'This token was last used {time}. Reinstall it on another machine and this updates.',
    pausedTitle: 'No connection yet',
    pausedBody: 'Stopped checking on its own. Press Check again once it is set up.',
    goneTitle: 'This token no longer works',
    goneBody: 'It was deleted or replaced. Generate a new configuration.',
    goneBodyDsh: 'The token was regenerated or deleted elsewhere. Reload the page and copy again.',
    checkAgain: 'Check again',
    checking: 'Checking…',
    tipsToggle: 'Can’t connect?',
    justNow: 'just now',
    tips: {
      agentBrowser: 'No authorization page opened? Ask the Agent for the sign-in command (such as claude mcp login aigc-news) and run it in your own terminal, or press the login button in your client’s MCP settings.',
      agentAccount: 'Sign in on the authorization page with the account you are using here: allowing it from another account does not show up on this page.',
      agentNetwork: 'A company network or proxy may block aigcnews.cn. Try another network, or use Manual setup on this page.',
      manualConfig: 'Check that the configuration was merged into your client’s MCP settings (each client keeps them in its own file) and is still valid JSON.',
      restart: 'Restart the client or open a new session: most clients read their MCP settings only at startup.',
      latest: 'Every Generate makes a new token and only the newest one is watched here, so use the configuration you copied last.',
      network: 'A company network or proxy may block this site. Try another network, or ask your administrator to allow this site’s domain.',
      dshConfig: 'Run dsh --profile web --dump-config and check that the dsh-aigc-radar layer is there with a non-empty mcpToken.',
      dshRestart: "Restart dsh (npx {'@'}deepseek-ai/dsh web) after installing: a running dsh does not reload its config.",
      dshAsk: 'The plugin connects on its first search. Ask dsh something like “is there a ready-made RAG framework?”',
      dshRotated: 'Pressed {rotate}? The old token stopped working at once: copy the prompt for your Agent again, or rerun the install command.',
    },
  },
}

const zhCN: McpConnectionMessages = {
  mcpConnection: {
    agent: {
      waitingTitle: '等待 Agent 完成配置…',
      waitingBody: '把提示词粘给你的 Agent。它装好后，浏览器会打开本站授权页，你点「同意」，这里就会变成「已接入」。',
      authorizedTitle: '{client} 已获授权，等它连上…',
      authorizedTitleUnnamed: '已授权，等客户端连上…',
      authorizedBody: '授权已经完成。客户端第一次调用 AIGC Radar 时，这里就会变成「已接入」；有的客户端要重启或新开会话才会连。',
      connectedTitle: '已接入',
      connectedBody: '{client} 在 {time} 连上了 AIGC Radar。',
      connectedBodyUnnamed: '客户端在 {time} 连上了 AIGC Radar。',
      pausedTitle: '还没检测到接入',
      pausedBody: '已停止自动检测，授权完成后点「再检查」。',
    },
    manual: {
      waitingTitle: '等待客户端连接…',
      waitingBody: '把配置填进客户端并重启它；它一连上 AIGC Radar，这里就会变成「已连接」。',
      connectedBody: '客户端在 {time} 用这枚 Token 连上了 AIGC Radar。',
    },
    waitingTitle: '等待 {client} 连接…',
    waitingBodyDsh: 'Agent 装好后重启 dsh，再问它一个 AI 项目相关的问题；插件第一次搜索时，这里就会变成「已连接」。',
    connectedTitle: '已连接',
    connectedBody: '{client} 在 {time} 用这枚 Token 连上了 AIGC Radar。',
    seenTitle: '以前连上过',
    seenBody: '这枚 Token 最近一次使用是{time}。换台电脑重新安装后，这里会刷新。',
    pausedTitle: '还没检测到连接',
    pausedBody: '已停止自动检测，装好后点「再检查」。',
    goneTitle: '这枚 Token 已失效',
    goneBody: '它已被删除或替换，请重新生成一份配置。',
    goneBodyDsh: 'Token 已在别处重新生成或删除，刷新页面后再复制一次。',
    checkAgain: '再检查',
    checking: '检查中…',
    tipsToggle: '连不上？',
    justNow: '刚刚',
    tips: {
      agentBrowser: '授权页没打开：请 Agent 告诉你授权命令（例如 claude mcp login aigc-news），在自己的终端里运行；也可以在客户端的 MCP 设置里点登录。',
      agentAccount: '在授权页登录的要是现在这个账号；用别的账号点了「同意」，这里看不到。',
      agentNetwork: '公司网络或代理可能拦着 aigcnews.cn：换个网络再试，或改用页面上的「手动配置」。',
      manualConfig: '确认这段配置合并进了客户端的 MCP 配置（各客户端的文件位置不同），合并后仍是合法的 JSON。',
      restart: '重启客户端或新开一个会话：多数客户端只在启动时读取 MCP 配置。',
      latest: '每次「生成」都是一枚新 Token，这里只认最新那一枚：请用最后复制的那份配置。',
      network: '公司网络或代理可能拦着本站：换个网络再试，或请管理员放行本站域名。',
      dshConfig: '运行 dsh --profile web --dump-config，确认有 dsh-aigc-radar 配置层、mcpToken 不为空。',
      dshRestart: "装好后要重启 dsh（npx {'@'}deepseek-ai/dsh web），正在运行的 dsh 不会重新读取配置。",
      dshAsk: '插件在第一次搜索时才连接：在 dsh 里问一句「有没有现成的 RAG 框架」试试。',
      dshRotated: '点过「{rotate}」？旧 Token 立即失效：把提示词重新复制给 Agent，或重新运行安装命令。',
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
