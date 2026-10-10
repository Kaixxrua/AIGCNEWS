import i18n from '@/i18n'

/**
 * /mcp 与 /dsh「复制给 Agent 的配置提示词」页面的文案，沿用 mcpConnection.ts 的注入方式：
 * 主 locale 表的 mcp/dsh 段由其他工作流维护，这里在页面初始化时经 mergeLocaleMessage 注入 agentSetup.*。
 * 不分组的几条两页共用；提示词正文本身不在这里（含命令与 JSON，见 features/mcp/agentSetupPrompt.ts）。
 * 消息里不写 @ | { }（vue-i18n 的语法字符），要用时按 {'@'} 转义。
 */

type StoryStep = { title: string; body: string }

type AgentSetupMessages = {
  agentSetup: {
    copyPrompt: string
    copied: string
    loginToCopy: string
    previewShow: string
    previewHide: string
    previewLabel: string
    stepsLabel: string
    loginForStatus: string
    mcp: {
      kicker: string
      oauth: string
      noToken: string
      description: string
      lede: string
      steps: { copy: StoryStep; paste: StoryStep; allow: StoryStep }
      hint: string
      guestHint: string
      endpoint: { title: string; body: string; copy: string }
      manual: {
        title: string
        summary: string
        generate: string
        creating: string
        copy: string
        login: string
        retry: string
        note: string
      }
      tier: { member: string; free: string }
      examples: { title: string; body: string }
    }
    dsh: {
      lede: string
      steps: { copy: StoryStep; paste: StoryStep; ask: StoryStep }
      hint: string
      guestHint: string
      manual: { title: string; summary: string }
    }
  }
}

const zhCN: AgentSetupMessages = {
  agentSetup: {
    copyPrompt: '复制给 Agent 的配置提示词',
    copied: '已复制，去粘给你的 Agent',
    loginToCopy: '登录后复制提示词',
    previewShow: '看看提示词',
    previewHide: '收起提示词',
    previewLabel: '提示词全文',
    stepsLabel: '接入三步',
    loginForStatus: '登录查看接入状态',
    mcp: {
      kicker: '一键接入',
      oauth: '浏览器授权',
      noToken: '不用复制 Token',
      description: '接好后，你的 Agent 可以直接检索本站收录的 AI 项目、开源软件、论文和 UI 模板，还能读你的个人收藏（vip 还能读追踪结果）。',
      lede: '点一下复制配置提示词，粘给你正在用的 AI 编程 Agent（Claude Code、Codex、Cursor、VS Code 等）。它会自己把 AIGC Radar 加进客户端；浏览器弹出授权页时，你点「同意」就好。',
      steps: {
        copy: { title: '复制提示词', body: '不含 Token，游客也能复制' },
        paste: { title: '粘给 Agent', body: '它自己认出客户端、运行命令' },
        allow: { title: '浏览器里点「同意」', body: '授权后这里显示「已接入」' },
      },
      hint: '授权页会请你登录本站账号；接好后，这里显示接入状态和你的额度。',
      guestHint: '授权时本站会请你登录。想在这页看到接入状态，也在这里登录一下。',
      endpoint: {
        title: '只能填网址的客户端',
        body: '有的客户端只让你粘一个远程 MCP 地址：填这一行，连接时它会打开浏览器请你授权。',
        copy: '复制地址',
      },
      manual: {
        title: '手动配置',
        summary: '客户端不支持浏览器授权，或者想自己排查时用：生成一枚 Token，把这段配置合并进客户端的 MCP 配置。',
        generate: '生成配置',
        creating: '正在生成 Token…',
        copy: '复制配置',
        login: '登录后生成',
        retry: '重试',
        note: 'Token 只写进你复制的配置，页面上不显示；每次生成都是新的一枚，可以和已有的同时使用。',
      },
      tier: {
        member: '当前档位 vip：每 24 小时 {daily} 次、每 30 天 {monthly} 次。',
        free: '当前档位 Free：每 24 小时 {daily} 次、每 30 天 {monthly} 次。',
      },
      examples: {
        title: '接好后这样问',
        body: '把任意一句发给已接好的 Agent。',
      },
    },
    dsh: {
      lede: '点一下复制配置提示词，粘给你的 AI 编程 Agent：它会装好 dsh-aigc-radar 插件，再把你账号的专属 Token 写进 dsh 的 web 配置。',
      steps: {
        copy: { title: '复制提示词', body: '带着你的专属 Token，只进剪贴板' },
        paste: { title: '粘给 Agent', body: '它装插件、写配置' },
        ask: { title: '重启 dsh 问一句', body: '第一次搜索后这里显示「已连接」' },
      },
      hint: 'Token 与账号绑定，刷新后不变；提示词里带着它，别分享给别人。',
      guestHint: '提示词要带上你账号的专属 Token，所以先登录；Token 不会显示在页面上。',
      manual: {
        title: '手动安装',
        summary: '不经过 Agent：选一种安装方式，复制命令在终端里运行。',
      },
    },
  },
}

const enUS: AgentSetupMessages = {
  agentSetup: {
    copyPrompt: 'Copy the setup prompt for your Agent',
    copied: 'Copied. Paste it to your Agent',
    loginToCopy: 'Sign in to copy the prompt',
    previewShow: 'Show the prompt',
    previewHide: 'Hide the prompt',
    previewLabel: 'The full prompt',
    stepsLabel: 'Three steps',
    loginForStatus: 'Sign in to see the status',
    mcp: {
      kicker: 'One-click setup',
      oauth: 'Browser sign-in',
      noToken: 'No token to copy',
      description: 'Once connected, your Agent can search the AI projects, open-source software, papers and UI templates collected here, and read your saved items (vip members also get their tracking results).',
      lede: 'Copy the setup prompt and paste it to the AI coding agent you already use (Claude Code, Codex, Cursor, VS Code and others). It adds AIGC Radar to its client by itself; when the authorization page opens in your browser, click Allow.',
      steps: {
        copy: { title: 'Copy the prompt', body: 'It holds no token, so anyone can copy it' },
        paste: { title: 'Paste it to your Agent', body: 'It works out the client and runs the commands' },
        allow: { title: 'Click Allow in the browser', body: 'This page then shows Connected' },
      },
      hint: 'The authorization page asks you to sign in to this site. Once connected, this page shows the status and your quota.',
      guestHint: 'You sign in when you authorize. To follow the status on this page, sign in here as well.',
      endpoint: {
        title: 'Clients that only take a URL',
        body: 'Some clients only ask for a remote MCP URL. Give them this one, and they open the browser for you to authorize when they connect.',
        copy: 'Copy URL',
      },
      manual: {
        title: 'Manual setup',
        summary: 'For clients without browser authorization, or to troubleshoot: generate a token and merge this configuration into the client’s MCP configuration.',
        generate: 'Generate',
        creating: 'Creating a token…',
        copy: 'Copy configuration',
        login: 'Sign in to generate',
        retry: 'Try again',
        note: 'The token only goes into the configuration you copy and never shows on the page. Each one you generate is new and works alongside the others.',
      },
      tier: {
        member: 'Your tier: vip, {daily} calls per 24 hours and {monthly} per 30 days.',
        free: 'Your tier: Free, {daily} calls per 24 hours and {monthly} per 30 days.',
      },
      examples: {
        title: 'Once connected, ask',
        body: 'Send any of these to the connected Agent.',
      },
    },
    dsh: {
      lede: 'Copy the setup prompt and paste it to your AI coding agent: it installs the dsh-aigc-radar plugin and writes your account’s personal token into dsh’s web profile.',
      steps: {
        copy: { title: 'Copy the prompt', body: 'It carries your personal token, straight to the clipboard' },
        paste: { title: 'Paste it to your Agent', body: 'It installs the plugin and writes the configuration' },
        ask: { title: 'Restart dsh and ask', body: 'After the first search this page shows Connected' },
      },
      hint: 'The token belongs to your account and stays the same across reloads. The prompt carries it, so do not share it.',
      guestHint: 'The prompt carries your account’s personal token, so sign in first. The token never shows on the page.',
      manual: {
        title: 'Install by hand',
        summary: 'Skip the Agent: pick an install method, copy the command and run it in your terminal.',
      },
    },
  },
}

/** 只给自带精简文案表的组件测试用：把这段并进测试自己的 i18n。 */
export const agentSetupMessages = { 'en-US': enUS, 'zh-CN': zhCN } as const

let installed = false

export function installAgentSetupMessages(): void {
  if (installed) return
  installed = true
  i18n.global.mergeLocaleMessage('en-US', enUS)
  i18n.global.mergeLocaleMessage('zh-CN', zhCN)
}
